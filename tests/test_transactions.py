"""Tests for excluded column on transactions_norm (BUG-17, Option A)."""

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
    """Seed transactions_norm rows.

    Each row is (fingerprint, merchant, amount, excluded).
    ``excluded`` may be True, False, or None.
    """
    conn = get_connection(db_path)
    for fp, merchant, amount, excluded in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, "
            " excluded, statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'desc', ?, ?, 'Food', 'Restaurants', 'Food & Dining', ?, "
            "'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
            [fp, amount, merchant, excluded],
        )
    conn.close()


# ---------------------------------------------------------------------------
# 1. excluded column exists in schema
# ---------------------------------------------------------------------------

def test_excluded_column_exists_in_schema(tmp_path: Path):
    """The excluded column must exist in transactions_norm with BOOLEAN type."""
    _client, db_path = _make_client(tmp_path)

    # Ensure DB is created (read-write first)
    conn = get_connection(db_path)
    conn.close()

    conn = get_connection(db_path, read_only=True)
    row = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = 'transactions_norm' AND column_name = 'excluded'"
    ).fetchone()
    conn.close()

    assert row is not None, "excluded column does not exist"
    assert row[0] == "BOOLEAN", f"excluded column type is {row[0]}, expected BOOLEAN"


# ---------------------------------------------------------------------------
# 2. PATCH /transactions/{fp} with excluded field works
# ---------------------------------------------------------------------------

def test_patch_transaction_excluded_field_works(tmp_path: Path):
    """PATCH with excluded=True should succeed (no DuckDB error)."""
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Starbucks", -5.00, False),
    ])

    resp = client.patch("/transactions/fp1", json={"excluded": True})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    conn = get_connection(db_path, read_only=True)
    row = conn.execute(
        "SELECT excluded FROM transactions_norm WHERE transaction_fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert row[0] is True


# ---------------------------------------------------------------------------
# 3. Excluded transactions hidden by default in GET /transactions
# ---------------------------------------------------------------------------

def test_excluded_transactions_hidden_by_default(tmp_path: Path):
    """GET /transactions should not return excluded transactions by default."""
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Starbucks", -5.00, False),
        ("fp2", "Target",    -25.00, False),
        ("fp3", "Costco",    -100.00, True),
    ])

    resp = client.get("/transactions", params={"type": "bank"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    fps = [r["transaction_fingerprint"] for r in data["rows"]]
    assert "fp3" not in fps


# ---------------------------------------------------------------------------
# 4. Normalization skips excluded transactions
# ---------------------------------------------------------------------------

def test_normalization_skips_excluded_transactions(tmp_path: Path):
    """Normalization paths should not modify excluded transactions."""
    from finance_etl.merchant_rules import batch_renormalize, create_normalization_job

    _client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp_ex", "Starbucks", -5.00, True),
    ])

    # Seed a merchant rule
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO merchant_rules (pattern, match_type, merchant, priority, created_at, updated_at) "
        "VALUES ('desc', 'contains', 'NewMerchant', 0, '2024-01-01', '2024-01-01')"
    )
    conn.execute(
        "INSERT INTO merchant_category_map (merchant, category, source, updated_at) "
        "VALUES ('NewMerchant', 'Coffee', 'user', '2024-01-01')"
    )
    job_id = create_normalization_job(conn)
    conn.close()

    batch_renormalize(str(db_path), job_id)

    conn = get_connection(db_path, read_only=True)
    row = conn.execute(
        "SELECT merchant, category FROM transactions_norm "
        "WHERE transaction_fingerprint = 'fp_ex'"
    ).fetchone()
    conn.close()
    # Excluded transaction should NOT have been re-normalized
    assert row[0] == "Starbucks", "Excluded transaction merchant was modified by normalization"
