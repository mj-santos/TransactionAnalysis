"""Tests for bulk action endpoints: bulk-assign-merchant and merchant search."""

from pathlib import Path

import pytest

from finance_etl.db import get_connection


def _make_client(tmp_path):
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    return TestClient(app), db_path


def _seed_transactions(db_path, rows):
    """Seed transactions_norm rows.  Each row is (fingerprint, merchant, category, amount)."""
    conn = get_connection(db_path)
    for fp, merchant, category, amount in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, category, "
            " statement_type, run_id, bank_name, account_name, account_id, source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'desc', ?, ?, ?, 'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
            [fp, amount, merchant, category],
        )
    conn.close()


def _seed_merchant_category(db_path, merchant, category):
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO merchant_category_map (merchant, category, source, updated_at) "
        "VALUES (?, ?, 'user', '2024-01-01T00:00:00')",
        [merchant, category],
    )
    conn.close()


# ---------------------------------------------------------------------------
# Test 1: bulk-assign-merchant updates all fingerprints
# ---------------------------------------------------------------------------

def test_bulk_assign_merchant_updates_all_fingerprints(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "OldMerchant", "Food", -10),
        ("fp2", "OldMerchant", "Food", -20),
        ("fp3", "Other", "Shopping", -30),
    ])

    resp = client.patch("/transactions/bulk-assign-merchant", json={
        "fingerprints": ["fp1", "fp2"],
        "merchant_normalized": "NewMerchant",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == 2

    conn = get_connection(db_path, read_only=True)
    r1 = conn.execute(
        "SELECT merchant FROM transactions_norm WHERE transaction_fingerprint='fp1'"
    ).fetchone()
    r2 = conn.execute(
        "SELECT merchant FROM transactions_norm WHERE transaction_fingerprint='fp2'"
    ).fetchone()
    r3 = conn.execute(
        "SELECT merchant FROM transactions_norm WHERE transaction_fingerprint='fp3'"
    ).fetchone()
    conn.close()
    assert r1[0] == "NewMerchant"
    assert r2[0] == "NewMerchant"
    assert r3[0] == "Other"  # unchanged


# ---------------------------------------------------------------------------
# Test 2: bulk-assign-merchant applies category if mapping exists
# ---------------------------------------------------------------------------

def test_bulk_assign_merchant_applies_category_if_mapping_exists(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "OldMerch", "Uncategorized", -10),
        ("fp2", "OldMerch", "Uncategorized", -20),
    ])
    _seed_merchant_category(db_path, "Starbucks", "Coffee Shops")

    resp = client.patch("/transactions/bulk-assign-merchant", json={
        "fingerprints": ["fp1", "fp2"],
        "merchant_normalized": "Starbucks",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == 2
    assert data["categorized"] == 2

    conn = get_connection(db_path, read_only=True)
    cats = conn.execute(
        "SELECT category FROM transactions_norm WHERE transaction_fingerprint IN ('fp1','fp2') ORDER BY transaction_fingerprint"
    ).fetchall()
    conn.close()
    assert all(c[0] == "Coffee Shops" for c in cats)


# ---------------------------------------------------------------------------
# Test 3: bulk-assign-merchant does NOT change category when no mapping
# ---------------------------------------------------------------------------

def test_bulk_assign_merchant_no_category_if_no_mapping(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "OldMerch", "Food", -10),
    ])

    resp = client.patch("/transactions/bulk-assign-merchant", json={
        "fingerprints": ["fp1"],
        "merchant_normalized": "UnknownMerchant",
    })
    data = resp.json()
    assert data["updated"] == 1
    assert data["categorized"] == 0

    conn = get_connection(db_path, read_only=True)
    row = conn.execute(
        "SELECT category FROM transactions_norm WHERE transaction_fingerprint='fp1'"
    ).fetchone()
    conn.close()
    assert row[0] == "Food"  # unchanged


# ---------------------------------------------------------------------------
# Test 4: merchant search returns frequency-ordered results
# ---------------------------------------------------------------------------

def test_merchant_search_returns_frequency_ordered_results(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Walmart", "Shopping", -10),
        ("fp2", "Walmart", "Shopping", -20),
        ("fp3", "Walmart", "Shopping", -30),
        ("fp4", "Walgreens", "Health", -5),
    ])

    resp = client.get("/merchants/search?q=wal&limit=10")
    assert resp.status_code == 200
    merchants = resp.json()["merchants"]
    assert len(merchants) == 2
    # Walmart has 3 txns, Walgreens has 1 — Walmart should be first
    assert merchants[0]["merchant"] == "Walmart"
    assert merchants[0]["count"] == 3
    assert merchants[1]["merchant"] == "Walgreens"
    assert merchants[1]["count"] == 1


# ---------------------------------------------------------------------------
# Test 5: merchant search is case-insensitive
# ---------------------------------------------------------------------------

def test_merchant_search_case_insensitive(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Starbucks", "Coffee", -5),
        ("fp2", "STARBUCKS", "Coffee", -5),
    ])

    # Search lowercase
    resp = client.get("/merchants/search?q=starbucks&limit=10")
    assert resp.status_code == 200
    merchants = resp.json()["merchants"]
    # Both variants should be returned (DuckDB treats them as distinct merchants)
    assert len(merchants) >= 1
    names_lower = [m["merchant"].lower() for m in merchants]
    assert all("starbucks" in n for n in names_lower)
