"""Tests for inline category editing, category_override, and merchant category management."""

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
    """Seed transactions_norm rows.  Each row is (fingerprint, merchant, category_normalized, amount, override)."""
    conn = get_connection(db_path)
    for fp, merchant, cat_norm, amount, override in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category_normalized, category_parent, category_override, "
            " statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'desc', ?, ?, ?, 'Food & Dining', ?, "
            "'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
            [fp, amount, merchant, cat_norm, override],
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
# 1. PATCH /transactions/{fp} sets category_override
# ---------------------------------------------------------------------------

def test_transaction_patch_sets_category_override(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Starbucks", "Coffee", -5.00, False),
    ])

    resp = client.patch("/transactions/fp1", json={
        "category_normalized": "Restaurants",
        "category_parent": "Food & Dining",
        "category_override": True,
    })
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    conn = get_connection(db_path, read_only=True)
    row = conn.execute(
        "SELECT category_normalized, category_parent, category_override "
        "FROM transactions_norm WHERE transaction_fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert row[0] == "Restaurants"
    assert row[1] == "Food & Dining"
    assert row[2] == True


# ---------------------------------------------------------------------------
# 2. Normalization skips override transactions
# ---------------------------------------------------------------------------

def test_normalization_skips_override_transactions(tmp_path: Path):
    from finance_etl.category_rules import apply_category_rules
    import uuid

    db_path = tmp_path / "test.duckdb"
    # Bootstrap DB schema
    conn = get_connection(db_path)

    # Insert transactions directly (not using _seed which also opens get_connection)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, merchant, "
        " category_normalized, category_parent, category_override, "
        " statement_type, run_id, bank_name, account_name, account_id, "
        " source_file, source_row, file_hash) "
        "VALUES ('fp_manual', '2024-06-01', 'desc', -5, 'Starbucks', 'ManualCategory', "
        "'Food & Dining', TRUE, 'bank', 'r1', 'B', 'A', 'a1', 'f.csv', 1, 'h1')"
    )
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, merchant, "
        " category_normalized, category_parent, category_override, "
        " statement_type, run_id, bank_name, account_name, account_id, "
        " source_file, source_row, file_hash) "
        "VALUES ('fp_auto', '2024-06-01', 'desc', -5, 'Starbucks', 'OldCategory', "
        "'Food & Dining', FALSE, 'bank', 'r1', 'B', 'A', 'a1', 'f.csv', 1, 'h1')"
    )

    # Verify the override was set correctly
    check = conn.execute(
        "SELECT transaction_fingerprint, category_override FROM transactions_norm ORDER BY transaction_fingerprint"
    ).fetchall()
    assert check[0] == ('fp_auto', False)
    assert check[1] == ('fp_manual', True)

    # Create normalization job
    job_id = f"catnorm_{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO normalization_jobs (job_id, status, created_at) "
        "VALUES (?, 'pending', '2024-01-01')",
        [job_id],
    )
    conn.close()

    apply_category_rules(str(db_path), job_id)

    # Verify: override row untouched, auto row updated
    conn3 = get_connection(db_path, read_only=True)
    manual = conn3.execute(
        "SELECT category_normalized FROM transactions_norm "
        "WHERE transaction_fingerprint = 'fp_manual'"
    ).fetchone()
    conn3.close()

    assert manual[0] == "ManualCategory"  # NOT changed by normalization


# ---------------------------------------------------------------------------
# 3. Override reset re-applies normalization eligibility
# ---------------------------------------------------------------------------

def test_override_reset_makes_row_eligible(tmp_path: Path):
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Starbucks", "ManualCat", -5.00, True),
    ])

    # Reset the override
    resp = client.patch("/transactions/fp1", json={
        "category_override": False,
    })
    assert resp.status_code == 200

    conn = get_connection(db_path, read_only=True)
    row = conn.execute(
        "SELECT category_override FROM transactions_norm "
        "WHERE transaction_fingerprint = 'fp1'"
    ).fetchone()
    conn.close()
    assert row[0] == False


# ---------------------------------------------------------------------------
# 4. Fix-for-all skips existing overrides
# ---------------------------------------------------------------------------

def test_fix_for_all_skips_existing_overrides(tmp_path: Path):
    """Verify that when updating all transactions for a merchant,
    rows with category_override=TRUE are not affected."""
    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Starbucks", "ManualCat", -5.00, True),   # has override
        ("fp2", "Starbucks", "OldCat", -10.00, False),    # no override
        ("fp3", "Starbucks", "OldCat", -15.00, False),    # no override
    ])

    # Simulate "Fix for all" by assigning merchant category and
    # patching non-override transactions
    _seed_merchant_category(db_path, "Starbucks", "NewCat")

    # Patch only non-override rows (as the JS would do)
    resp2 = client.patch("/transactions/fp2", json={
        "category_normalized": "NewCat",
        "category_parent": "Food & Dining",
    })
    assert resp2.status_code == 200
    resp3 = client.patch("/transactions/fp3", json={
        "category_normalized": "NewCat",
        "category_parent": "Food & Dining",
    })
    assert resp3.status_code == 200

    # Verify: fp1 (override) unchanged, fp2 and fp3 updated
    conn = get_connection(db_path, read_only=True)
    r1 = conn.execute(
        "SELECT category_normalized FROM transactions_norm WHERE transaction_fingerprint = 'fp1'"
    ).fetchone()
    r2 = conn.execute(
        "SELECT category_normalized FROM transactions_norm WHERE transaction_fingerprint = 'fp2'"
    ).fetchone()
    r3 = conn.execute(
        "SELECT category_normalized FROM transactions_norm WHERE transaction_fingerprint = 'fp3'"
    ).fetchone()
    conn.close()

    assert r1[0] == "ManualCat"  # override preserved
    assert r2[0] == "NewCat"
    assert r3[0] == "NewCat"


# ---------------------------------------------------------------------------
# 5. Merchant list bulk category assign
# ---------------------------------------------------------------------------

def test_merchant_list_bulk_category_assign(tmp_path: Path):
    client, db_path = _make_client(tmp_path)

    # Assign categories to multiple merchants
    resp1 = client.post("/merchant-categories", json={
        "merchant": "Merchant1",
        "category": "Category1",
    })
    assert resp1.status_code in (200, 201)

    resp2 = client.post("/merchant-categories", json={
        "merchant": "Merchant2",
        "category": "Category2",
    })
    assert resp2.status_code in (200, 201)

    # Verify both exist
    resp = client.get("/merchant-categories")
    assert resp.status_code == 200
    cats = resp.json()["categories"]
    merchants = {c["merchant"]: c["category"] for c in cats}
    assert merchants["Merchant1"] == "Category1"
    assert merchants["Merchant2"] == "Category2"


# ---------------------------------------------------------------------------
# 6. Merchant list bulk category remove
# ---------------------------------------------------------------------------

def test_merchant_list_bulk_category_remove(tmp_path: Path):
    client, db_path = _make_client(tmp_path)

    # Add then remove
    client.post("/merchant-categories", json={
        "merchant": "ToRemove",
        "category": "SomeCategory",
    })

    resp = client.delete("/merchant-categories/ToRemove")
    assert resp.status_code == 200

    # Verify it's gone
    resp2 = client.get("/merchant-categories")
    cats = resp2.json()["categories"]
    merchants = [c["merchant"] for c in cats]
    assert "ToRemove" not in merchants


# ---------------------------------------------------------------------------
# 7. Bulk category assignment with override survives renormalization
# ---------------------------------------------------------------------------

def test_bulk_category_with_override_survives_renormalization(tmp_path: Path):
    """Simulate bulk category assignment (PATCH with category_override=true)
    and verify the categories are preserved after a full batch renormalization."""
    from finance_etl.merchant_rules import batch_renormalize, create_normalization_job

    client, db_path = _make_client(tmp_path)
    _seed_transactions(db_path, [
        ("fp1", "Acme Corp", None, -10.00, False),
        ("fp2", "Acme Corp", None, -20.00, False),
    ])

    # Simulate bulk category assignment (as the frontend now does)
    for fp in ("fp1", "fp2"):
        resp = client.patch(f"/transactions/{fp}", json={
            "category_normalized": "Office Supplies",
            "category_parent": "Business",
            "category_override": True,
        })
        assert resp.status_code == 200

    # Run a full batch renormalization synchronously
    conn = get_connection(db_path)
    job_id = create_normalization_job(conn)
    conn.close()
    batch_renormalize(str(db_path), job_id)

    # Verify overridden categories survived
    conn = get_connection(db_path, read_only=True)
    rows = conn.execute(
        "SELECT transaction_fingerprint, category_normalized, category_override "
        "FROM transactions_norm ORDER BY transaction_fingerprint"
    ).fetchall()
    conn.close()

    for fp, cat, override in rows:
        assert cat == "Office Supplies", f"{fp} category was overwritten by renormalization"
        assert override == True, f"{fp} category_override was cleared"
