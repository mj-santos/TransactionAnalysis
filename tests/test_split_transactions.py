"""Tests for split transaction UI wiring and endpoints."""

import io
import json
from pathlib import Path

import pytest

from finance_etl.db import get_connection


def _make_client(tmp_path):
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    return TestClient(app), db_path


def _seed_transaction(db_path, fp, amount, merchant="TestMerchant", description="desc"):
    """Insert a single transaction into transactions_norm."""
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, merchant, "
        " category, category_normalized, category_parent, "
        " statement_type, run_id, bank_name, account_name, account_id, "
        " source_file, source_row, file_hash) "
        "VALUES (?, '2024-06-15', ?, ?, ?, 'Food', 'Restaurants', 'Food & Dining', "
        "'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
        [fp, description, amount, merchant],
    )
    conn.close()


# ---------------------------------------------------------------------------
# 1. POST /transactions/{fp}/split creates children
# ---------------------------------------------------------------------------

def test_split_endpoint_creates_children(tmp_path: Path):
    """Splitting a transaction creates child rows and marks parent."""
    client, db_path = _make_client(tmp_path)
    _seed_transaction(db_path, "fp_parent", -100.00)

    resp = client.post("/transactions/fp_parent/split", json={
        "splits": [
            {"amount": -60.00, "category": "Groceries"},
            {"amount": -40.00, "category": "Household"},
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["parent"] == "fp_parent"
    assert data["children"] == 2

    conn = get_connection(db_path, read_only=True)
    # Parent marked as split
    parent = conn.execute(
        "SELECT is_split FROM transactions_norm WHERE transaction_fingerprint = 'fp_parent'"
    ).fetchone()
    assert parent[0] is True

    # Children created with correct amounts
    children = conn.execute(
        "SELECT transaction_fingerprint, amount, split_parent_fingerprint "
        "FROM transactions_norm WHERE split_parent_fingerprint = 'fp_parent' "
        "ORDER BY transaction_fingerprint"
    ).fetchall()
    assert len(children) == 2
    amounts = sorted([float(c[1]) for c in children])
    assert amounts == [-60.00, -40.00]
    for c in children:
        assert c[2] == "fp_parent"
    conn.close()


# ---------------------------------------------------------------------------
# 2. Split parent excluded from totals; children counted
# ---------------------------------------------------------------------------

def test_split_parent_excluded_from_totals(tmp_path: Path):
    """After split, parent is excluded from query; children are counted."""
    client, db_path = _make_client(tmp_path)
    _seed_transaction(db_path, "fp_total", -100.00)

    # Split the transaction
    client.post("/transactions/fp_total/split", json={
        "splits": [
            {"amount": -60.00, "category": "Groceries"},
            {"amount": -40.00, "category": "Household"},
        ]
    })

    # GET /transactions should return children but not parent
    resp = client.get("/transactions", params={"type": "bank"})
    assert resp.status_code == 200
    data = resp.json()
    fps = [r["transaction_fingerprint"] for r in data["rows"]]
    assert "fp_total" not in fps  # parent excluded
    # Both children present
    child_fps = [f for f in fps if f.startswith("fp_total_split_")]
    assert len(child_fps) == 2


# ---------------------------------------------------------------------------
# 3. DELETE /transactions/{fp}/split restores parent
# ---------------------------------------------------------------------------

def test_unsplit_restores_parent(tmp_path: Path):
    """Unsplitting deletes children and restores parent."""
    client, db_path = _make_client(tmp_path)
    _seed_transaction(db_path, "fp_unsplit", -100.00)

    # Split
    client.post("/transactions/fp_unsplit/split", json={
        "splits": [
            {"amount": -60.00, "category": "A"},
            {"amount": -40.00, "category": "B"},
        ]
    })

    # Unsplit
    resp = client.delete("/transactions/fp_unsplit/split")
    assert resp.status_code == 200
    data = resp.json()
    assert data["children_removed"] == 2

    conn = get_connection(db_path, read_only=True)
    # Parent restored (is_split = FALSE)
    parent = conn.execute(
        "SELECT is_split FROM transactions_norm WHERE transaction_fingerprint = 'fp_unsplit'"
    ).fetchone()
    assert parent[0] is False

    # Children removed
    children = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm WHERE split_parent_fingerprint = 'fp_unsplit'"
    ).fetchone()
    assert children[0] == 0
    conn.close()

    # Parent appears in transactions again
    resp = client.get("/transactions", params={"type": "bank"})
    fps = [r["transaction_fingerprint"] for r in resp.json()["rows"]]
    assert "fp_unsplit" in fps


# ---------------------------------------------------------------------------
# 4. Split survives backup/restore
# ---------------------------------------------------------------------------

def test_split_survives_backup_restore(tmp_path: Path):
    """Split transactions round-trip through backup export and restore."""
    client, db_path = _make_client(tmp_path)
    _seed_transaction(db_path, "fp_bkup", -100.00)

    # Split
    client.post("/transactions/fp_bkup/split", json={
        "splits": [
            {"amount": -70.00, "category": "Travel"},
            {"amount": -30.00, "category": "Food"},
        ]
    })

    # Export backup
    resp = client.get("/backup/export")
    assert resp.status_code == 200
    backup_bytes = resp.content

    # Restore backup
    resp = client.post(
        "/backup/restore",
        files={"file": ("backup.json", io.BytesIO(backup_bytes), "application/json")},
    )
    assert resp.status_code == 200

    # Verify parent still marked as split
    conn = get_connection(db_path, read_only=True)
    parent = conn.execute(
        "SELECT is_split FROM transactions_norm WHERE transaction_fingerprint = 'fp_bkup'"
    ).fetchone()
    assert parent[0] is True

    # Verify children present with correct parent ref
    children = conn.execute(
        "SELECT transaction_fingerprint, amount, split_parent_fingerprint "
        "FROM transactions_norm WHERE split_parent_fingerprint = 'fp_bkup' "
        "ORDER BY transaction_fingerprint"
    ).fetchall()
    assert len(children) == 2
    amounts = sorted([float(c[1]) for c in children])
    assert amounts == [-70.00, -30.00]
    for c in children:
        assert c[2] == "fp_bkup"
    conn.close()


# ---------------------------------------------------------------------------
# 5. Split children cannot be split further
# ---------------------------------------------------------------------------

def test_split_children_cannot_be_split(tmp_path: Path):
    """Attempting to split a child row returns 400."""
    client, db_path = _make_client(tmp_path)
    _seed_transaction(db_path, "fp_no_resplit", -100.00)

    # Split
    client.post("/transactions/fp_no_resplit/split", json={
        "splits": [
            {"amount": -60.00, "category": "A"},
            {"amount": -40.00, "category": "B"},
        ]
    })

    # Try to split a child
    child_fp = "fp_no_resplit_split_0"
    resp = client.post(f"/transactions/{child_fp}/split", json={
        "splits": [
            {"amount": -30.00, "category": "X"},
            {"amount": -30.00, "category": "Y"},
        ]
    })
    assert resp.status_code == 400
    assert "child" in resp.json()["detail"].lower() or "split" in resp.json()["detail"].lower()
