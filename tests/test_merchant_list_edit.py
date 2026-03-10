"""Tests for Merchant List merchant-level category edit and orphan detection."""

from pathlib import Path

from finance_etl.db import get_connection


def _make_client(tmp_path):
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    return TestClient(app), db_path


def _seed(db_path, rows):
    """Seed transactions_norm rows.

    Each row is (fingerprint, merchant, category_normalized, amount, override, category_raw).
    """
    conn = get_connection(db_path)
    for i, (fp, merchant, cat_norm, amount, override, cat_raw) in enumerate(rows):
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, category_override, "
            " statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'desc', ?, ?, ?, ?, 'Food & Dining', ?, "
            "'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', ?, 'h1')",
            [fp, amount, merchant, cat_raw or '', cat_norm, override, i + 1],
        )
    conn.close()


# ---------------------------------------------------------------------------
# 1. One row per normalized merchant
# ---------------------------------------------------------------------------

def test_merchant_list_shows_one_row_per_normalized_merchant(tmp_path: Path):
    """Insert 10 transactions for Wendy's and 5 for Costco; merchant list returns exactly 2 rows."""
    client, db_path = _make_client(tmp_path)
    rows = []
    for i in range(10):
        rows.append((f"w{i}", "Wendy's", "Restaurants", -8.00, False, "Food"))
    for i in range(5):
        rows.append((f"c{i}", "Costco", "Groceries", -50.00, False, "Shopping"))
    _seed(db_path, rows)

    resp = client.get("/utilities/merchants")
    assert resp.status_code == 200
    data = resp.json()
    merchants = data["merchants"]
    names = [m["normalized_name"] for m in merchants]
    assert len(merchants) == 2, f"Expected 2 merchants, got {len(merchants)}: {names}"
    assert set(names) == {"Wendy's", "Costco"}
    wendys = next(m for m in merchants if m["normalized_name"] == "Wendy's")
    assert wendys["txn_count"] == 10
    costco = next(m for m in merchants if m["normalized_name"] == "Costco")
    assert costco["txn_count"] == 5


# ---------------------------------------------------------------------------
# 2. Category edit writes merchant_category_map, not transactions directly
# ---------------------------------------------------------------------------

def test_category_edit_writes_merchant_map_not_transactions(tmp_path: Path):
    """Assign category via POST /merchant-categories — should write to merchant_category_map
    and NOT set category_override=TRUE on any transaction."""
    client, db_path = _make_client(tmp_path)
    rows = [(f"t{i}", "Wendy's", None, -8.00, False, "Food") for i in range(5)]
    _seed(db_path, rows)

    resp = client.post("/merchant-categories", json={
        "merchant": "Wendy's",
        "category": "Fast Food",
        "parent": "Food & Dining",
        "source": "user",
    })
    assert resp.status_code == 201

    conn = get_connection(db_path, read_only=True)
    # Check merchant_category_map has the entry
    mcm = conn.execute(
        "SELECT category, source FROM merchant_category_map WHERE merchant = ?",
        ["Wendy's"],
    ).fetchone()
    assert mcm is not None, "merchant_category_map entry not found"
    assert mcm[0] == "Fast Food"
    assert mcm[1] == "user"

    # Check NO transactions have category_override=TRUE
    overrides = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm "
        "WHERE merchant = ? AND COALESCE(category_override, FALSE) = TRUE",
        ["Wendy's"],
    ).fetchone()[0]
    conn.close()
    assert overrides == 0, "Merchant-level edit must NOT set category_override"


# ---------------------------------------------------------------------------
# 3. Category edit re-normalizes all merchant transactions
# ---------------------------------------------------------------------------

def test_category_edit_renormalizes_all_merchant_transactions(tmp_path: Path):
    """Assign new category via merchant edit; all 10 transactions should update."""
    client, db_path = _make_client(tmp_path)
    rows = [(f"t{i}", "Wendy's", "OldCategory", -8.00, False, "Food") for i in range(10)]
    _seed(db_path, rows)

    resp = client.post("/merchant-categories", json={
        "merchant": "Wendy's",
        "category": "Fast Food",
        "parent": "Food & Dining",
        "source": "user",
    })
    assert resp.status_code == 201

    conn = get_connection(db_path, read_only=True)
    new_cat = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm "
        "WHERE merchant = ? AND category_normalized = 'Fast Food'",
        ["Wendy's"],
    ).fetchone()[0]
    old_cat = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm "
        "WHERE merchant = ? AND category_normalized = 'OldCategory'",
        ["Wendy's"],
    ).fetchone()[0]
    conn.close()
    assert new_cat == 10, f"Expected 10 transactions with new category, got {new_cat}"
    assert old_cat == 0, f"Expected 0 transactions with old category, got {old_cat}"


# ---------------------------------------------------------------------------
# 4. Category edit respects transaction-level overrides
# ---------------------------------------------------------------------------

def test_category_edit_respects_transaction_overrides(tmp_path: Path):
    """Transactions with category_override=TRUE must not be changed by merchant edit."""
    from finance_etl.merchant_rules import assign_category, renormalize_merchant
    import duckdb

    db_path = tmp_path / "test.duckdb"
    # Bootstrap schema once, seed data, set overrides — all on one connection
    conn = get_connection(db_path)
    for i in range(8):
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, category_override, "
            " statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'desc', -8, ?, 'Food', 'OldCategory', "
            "'Food & Dining', FALSE, 'bank', 'run1', 'B', 'A', 'a1', 'f.csv', ?, 'h1')",
            [f"t{i}", "Wendy's", i + 1],
        )
    for i in range(2):
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, category_override, "
            " statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'desc', -8, ?, 'Food', 'ManualCategory', "
            "'Food & Dining', TRUE, 'bank', 'run1', 'B', 'A', 'a1', 'f.csv', ?, 'h1')",
            [f"o{i}", "Wendy's", i + 1],
        )

    # Assign merchant-level category and re-normalize on same connection
    assign_category(conn, "Wendy's", "Fast Food", source="user")
    updated = renormalize_merchant(conn, "Wendy's")
    assert updated == 8, f"Expected 8 non-override transactions eligible, got {updated}"

    fast_food = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm "
        "WHERE merchant = ? AND category_normalized = 'Fast Food'",
        ["Wendy's"],
    ).fetchone()[0]
    manual = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm "
        "WHERE merchant = ? AND category_normalized = 'ManualCategory'",
        ["Wendy's"],
    ).fetchone()[0]
    conn.close()
    assert fast_food == 8, f"Expected 8 non-override transactions updated, got {fast_food}"
    assert manual == 2, f"Expected 2 override transactions unchanged, got {manual}"


# ---------------------------------------------------------------------------
# 5. Remove category triggers re-normalization
# ---------------------------------------------------------------------------

def test_remove_category_triggers_renormalization(tmp_path: Path):
    """After removing merchant category, transactions are re-normalized by rules."""
    client, db_path = _make_client(tmp_path)
    rows = [(f"t{i}", "Wendy's", "Fast Food", -8.00, False, "Food") for i in range(5)]
    _seed(db_path, rows)

    # First assign category
    resp = client.post("/merchant-categories", json={
        "merchant": "Wendy's",
        "category": "Fast Food",
        "source": "user",
    })
    assert resp.status_code == 201

    # Now remove it
    resp = client.delete("/merchant-categories/Wendy's")
    assert resp.status_code == 200

    conn = get_connection(db_path, read_only=True)
    # merchant_category_map should have no entry
    mcm = conn.execute(
        "SELECT COUNT(*) FROM merchant_category_map WHERE merchant = ?",
        ["Wendy's"],
    ).fetchone()[0]
    assert mcm == 0, "merchant_category_map entry should be removed"

    # Transactions should have been re-normalized (not still "Fast Food")
    # After removal, category_rules engine runs — with no matching rule,
    # category_normalized may be NULL or re-assigned by rules
    still_fast_food = conn.execute(
        "SELECT COUNT(*) FROM transactions_norm "
        "WHERE merchant = ? AND category_normalized = 'Fast Food'",
        ["Wendy's"],
    ).fetchone()[0]
    conn.close()
    # After re-normalization with no merchant_category_map entry,
    # the category should have been re-evaluated by category rules
    assert still_fast_food == 0, "Transactions should have been re-normalized after category removal"


# ---------------------------------------------------------------------------
# 6. Orphan detection catches stale category assignments
# ---------------------------------------------------------------------------

def test_orphan_detection_catches_stale_assignments(tmp_path: Path):
    """Directly changing merchant_category_map without re-normalizing creates orphans."""
    client, db_path = _make_client(tmp_path)
    rows = [(f"t{i}", "Wendy's", "OldCategory", -8.00, False, "Food") for i in range(5)]
    _seed(db_path, rows)

    # Directly insert into merchant_category_map WITHOUT re-normalizing
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO merchant_category_map (merchant, category, source, updated_at) "
        "VALUES ('Wendy''s', 'NewCategory', 'user', '2024-01-01T00:00:00')"
    )
    conn.close()

    resp = client.get("/utilities/health")
    assert resp.status_code == 200
    health = resp.json()
    assert health["orphaned_categories"] > 0, (
        f"Expected orphaned_categories > 0, got {health['orphaned_categories']}"
    )
