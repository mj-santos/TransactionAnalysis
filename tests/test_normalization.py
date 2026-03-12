"""Tests for normalization paths respecting category_override (BUG-16)."""

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

    Each row is (fingerprint, merchant, category, category_normalized, amount, override).
    ``override`` may be True, False, or None (to simulate NULL).
    """
    conn = get_connection(db_path)
    for fp, merchant, category, cat_norm, amount, override in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, category_override, "
            " statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', 'WENDYS #1234', ?, ?, ?, ?, 'Food & Dining', ?, "
            "'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
            [fp, amount, merchant, category, cat_norm, override],
        )
    conn.close()


def _seed_merchant_rule(db_path, pattern, merchant):
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO merchant_rules (pattern, match_type, merchant, priority, created_at, updated_at) "
        "VALUES (?, 'contains', ?, 0, '2024-01-01', '2024-01-01')",
        [pattern, merchant],
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


def _seed_transactions_with_desc(db_path, rows):
    """Seed transactions_norm rows with custom descriptions.

    Each row is (fingerprint, description, merchant, amount).
    """
    conn = get_connection(db_path)
    for fp, desc, merchant, amount in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, category_override, "
            " statement_type, run_id, bank_name, account_name, account_id, "
            " source_file, source_row, file_hash) "
            "VALUES (?, '2024-06-01', ?, ?, ?, NULL, NULL, NULL, FALSE, "
            "'bank', 'run1', 'TestBank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
            [fp, desc, amount, merchant],
        )
    conn.close()


# ---------------------------------------------------------------------------
# 1. batch_renormalize skips category_override=TRUE transactions
# ---------------------------------------------------------------------------

def test_batch_renormalize_skips_override_transactions(tmp_path: Path):
    """Override transactions keep their manual category after batch_renormalize."""
    from finance_etl.merchant_rules import batch_renormalize, create_normalization_job

    _client, db_path = _make_client(tmp_path)

    # 5 transactions for "Wendy's", 2 with category_override=TRUE
    _seed_transactions(db_path, [
        ("fp1", "Wendy's", "Fast Food", "Custom",    -10.00, True),
        ("fp2", "Wendy's", "Fast Food", "Custom",    -12.00, True),
        ("fp3", "Wendy's", "Fast Food", "Fast Food",  -8.00, False),
        ("fp4", "Wendy's", "Fast Food", "Fast Food",  -9.00, False),
        ("fp5", "Wendy's", "Fast Food", "Fast Food", -11.00, False),
    ])

    _seed_merchant_rule(db_path, "WENDYS", "Wendy's")
    _seed_merchant_category(db_path, "Wendy's", "Fast Food")

    conn = get_connection(db_path)
    job_id = create_normalization_job(conn)
    conn.close()

    batch_renormalize(str(db_path), job_id)

    conn = get_connection(db_path, read_only=True)
    # Override rows must still have "Custom"
    for fp in ("fp1", "fp2"):
        row = conn.execute(
            "SELECT category, category_normalized FROM transactions_norm "
            "WHERE transaction_fingerprint = ?", [fp]
        ).fetchone()
        assert row[1] == "Custom", f"{fp} override was clobbered"

    # Non-override rows should be updated normally
    for fp in ("fp3", "fp4", "fp5"):
        row = conn.execute(
            "SELECT merchant FROM transactions_norm "
            "WHERE transaction_fingerprint = ?", [fp]
        ).fetchone()
        assert row[0] == "Wendy's", f"{fp} merchant not updated"
    conn.close()


# ---------------------------------------------------------------------------
# 2. batch_renormalize treats NULL category_override as FALSE (not protected)
# ---------------------------------------------------------------------------

def test_batch_renormalize_treats_null_override_as_false(tmp_path: Path):
    """Rows with category_override=NULL are processed (not skipped)."""
    from finance_etl.merchant_rules import batch_renormalize, create_normalization_job

    _client, db_path = _make_client(tmp_path)

    # 3 transactions with category_override = NULL
    _seed_transactions(db_path, [
        ("fp1", None, None, None, -10.00, None),
        ("fp2", None, None, None, -12.00, None),
        ("fp3", None, None, None,  -8.00, None),
    ])

    _seed_merchant_rule(db_path, "WENDYS", "Wendy's")
    _seed_merchant_category(db_path, "Wendy's", "Fast Food")

    conn = get_connection(db_path)
    job_id = create_normalization_job(conn)
    conn.close()

    batch_renormalize(str(db_path), job_id)

    conn = get_connection(db_path, read_only=True)
    for fp in ("fp1", "fp2", "fp3"):
        row = conn.execute(
            "SELECT merchant FROM transactions_norm "
            "WHERE transaction_fingerprint = ?", [fp]
        ).fetchone()
        # These matched the WENDYS rule so should be normalized
        assert row[0] == "Wendy's", f"{fp} was not updated (NULL treated as protected)"
    conn.close()


# ---------------------------------------------------------------------------
# 3. All normalization paths skip overrides
# ---------------------------------------------------------------------------

def test_all_normalization_paths_skip_overrides(tmp_path: Path):
    """All three normalization paths must leave category_override=TRUE rows untouched."""
    from finance_etl.merchant_rules import batch_renormalize, create_normalization_job
    from finance_etl.category_rules import apply_category_rules

    client, db_path = _make_client(tmp_path)

    # Seed an override transaction
    _seed_transactions(db_path, [
        ("fp_o", "Wendy's", "Fast Food", "Custom", -10.00, True),
    ])
    _seed_merchant_rule(db_path, "WENDYS", "Wendy's")
    _seed_merchant_category(db_path, "Wendy's", "Fast Food")

    def _assert_custom():
        conn = get_connection(db_path, read_only=True)
        row = conn.execute(
            "SELECT category_normalized FROM transactions_norm "
            "WHERE transaction_fingerprint = 'fp_o'"
        ).fetchone()
        conn.close()
        assert row[0] == "Custom", "Override transaction was modified"

    # Path 1: batch_renormalize
    conn = get_connection(db_path)
    job_id = create_normalization_job(conn)
    conn.close()
    batch_renormalize(str(db_path), job_id)
    _assert_custom()

    # Path 2: apply_category_rules
    conn = get_connection(db_path)
    from finance_etl.category_rules import create_category_job
    cat_job_id = create_category_job(conn)
    conn.close()
    apply_category_rules(str(db_path), cat_job_id)
    _assert_custom()

    # Path 3: POST /normalize/apply with merchant_filter
    resp = client.post("/normalize/apply", json={"merchant_filter": "Wendy's"})
    assert resp.status_code in (200, 202)
    _assert_custom()


# ---------------------------------------------------------------------------
# 4. batch_renormalize updates category_normalized + category_parent (BUG-29)
# ---------------------------------------------------------------------------

def test_batch_renormalize_updates_category_normalized_and_parent(tmp_path: Path):
    """batch_renormalize must write to category_normalized and category_parent,
    not the raw category column. This was the root cause of the orphan categories
    Fix Now button being a no-op (BUG-29)."""
    from finance_etl.merchant_rules import batch_renormalize, create_normalization_job

    _client, db_path = _make_client(tmp_path)

    # Seed a transaction with wrong/NULL category_normalized but matching merchant
    _seed_transactions(db_path, [
        ("fp_orphan1", "Wendy's", "Fast Food", None, -10.00, False),
        ("fp_orphan2", "Wendy's", "Fast Food", "Wrong Category", -15.00, False),
    ])

    _seed_merchant_rule(db_path, "WENDYS", "Wendy's")
    _seed_merchant_category(db_path, "Wendy's", "Fast Food")

    conn = get_connection(db_path)
    job_id = create_normalization_job(conn)
    conn.close()

    batch_renormalize(str(db_path), job_id)

    conn = get_connection(db_path, read_only=True)
    for fp in ("fp_orphan1", "fp_orphan2"):
        row = conn.execute(
            "SELECT category_normalized, category_parent FROM transactions_norm "
            "WHERE transaction_fingerprint = ?", [fp]
        ).fetchone()
        assert row[0] == "Fast Food", (
            f"{fp}: category_normalized should be 'Fast Food', got {row[0]!r}"
        )
        assert row[1] is not None, (
            f"{fp}: category_parent should not be None"
        )
    conn.close()


# ---------------------------------------------------------------------------
# 5. Fuzzy merge groups similar descriptions
# ---------------------------------------------------------------------------

def test_fuzzy_merge_groups_similar_descriptions(tmp_path: Path):
    """Similar description cores should be merged into one suggestion group."""
    from finance_etl.merchant_rules import analyze_descriptions

    _client, db_path = _make_client(tmp_path)

    _seed_transactions_with_desc(db_path, [
        ("fp1", "BEST WESTERN INN S REEDSPORT OR", None, -120.00),
        ("fp2", "BEST WESTERN SEVEN S SAN DIEGO CA", None, -150.00),
        ("fp3", "BEST WESTERN PLUS PORTLAND OR", None, -130.00),
    ])

    conn = get_connection(db_path, read_only=True)
    suggestions = analyze_descriptions(
        conn, min_transactions=1, fuzzy_threshold=0.75, include_low_frequency=True,
    )
    conn.close()

    # All three Best Western variants should be in one group
    bw = [s for s in suggestions if "best western" in s["merchant"].lower()]
    assert len(bw) == 1, f"Expected 1 Best Western group, got {len(bw)}: {bw}"
    assert bw[0]["num_variants"] >= 2, "Should have merged multiple variants"
    assert bw[0]["fuzzy_merged"] is True


def test_fuzzy_does_not_merge_dissimilar(tmp_path: Path):
    """Dissimilar descriptions should remain separate groups."""
    from finance_etl.merchant_rules import analyze_descriptions

    _client, db_path = _make_client(tmp_path)

    _seed_transactions_with_desc(db_path, [
        ("fp1", "WALMART SUPERCENTER 1234", None, -80.00),
        ("fp2", "WALGREENS PHARMACY 5678", None, -25.00),
    ])

    conn = get_connection(db_path, read_only=True)
    suggestions = analyze_descriptions(
        conn, min_transactions=1, fuzzy_threshold=0.75, include_low_frequency=True,
    )
    conn.close()

    merchants = [s["merchant"].lower() for s in suggestions]
    # Both should appear as separate suggestions
    walmart = [m for m in merchants if "walmart" in m]
    walgreens = [m for m in merchants if "walgreens" in m]
    assert len(walmart) >= 1, "Walmart should appear"
    assert len(walgreens) >= 1, "Walgreens should appear"


# ---------------------------------------------------------------------------
# 6. auto_normalize_unmatched
# ---------------------------------------------------------------------------

def test_auto_normalize_unmatched(tmp_path: Path):
    """Auto-normalize sets merchant from description for NULL-merchant rows."""
    from finance_etl.merchant_rules import auto_normalize_unmatched

    _client, db_path = _make_client(tmp_path)

    _seed_transactions_with_desc(db_path, [
        ("fp1", "TRADER JOES #123 LOS ANGELES CA", None, -45.00),
        ("fp2", "COSTCO WHSE #456 SAN DIEGO CA", None, -200.00),
    ])

    conn = get_connection(db_path)
    count = auto_normalize_unmatched(conn)
    conn.close()

    assert count == 2

    conn = get_connection(db_path, read_only=True)
    r1 = conn.execute(
        "SELECT merchant FROM transactions_norm WHERE transaction_fingerprint='fp1'"
    ).fetchone()
    r2 = conn.execute(
        "SELECT merchant FROM transactions_norm WHERE transaction_fingerprint='fp2'"
    ).fetchone()
    conn.close()

    assert r1[0] is not None, "fp1 merchant should be set"
    assert r2[0] is not None, "fp2 merchant should be set"


def test_auto_normalize_skips_existing_merchants(tmp_path: Path):
    """Auto-normalize should not touch rows that already have a merchant."""
    from finance_etl.merchant_rules import auto_normalize_unmatched

    _client, db_path = _make_client(tmp_path)

    _seed_transactions_with_desc(db_path, [
        ("fp1", "TRADER JOES #123", "Trader Joe's", -45.00),
    ])

    conn = get_connection(db_path)
    count = auto_normalize_unmatched(conn)
    conn.close()

    assert count == 0


# ---------------------------------------------------------------------------
# 7. Low-frequency includes singletons
# ---------------------------------------------------------------------------

def test_low_frequency_includes_singletons(tmp_path: Path):
    """With include_low_frequency=True, single-transaction descriptions appear."""
    from finance_etl.merchant_rules import analyze_descriptions

    _client, db_path = _make_client(tmp_path)

    _seed_transactions_with_desc(db_path, [
        ("fp1", "UNIQUE COFFEE SHOP PORTLAND OR", None, -5.00),
    ])

    conn = get_connection(db_path, read_only=True)
    suggestions = analyze_descriptions(
        conn, min_transactions=3, include_low_frequency=True,
    )
    conn.close()

    # Should appear (count=1 < min_transactions=3 but include_low_frequency=True)
    assert len(suggestions) >= 1, "Singleton should appear with include_low_frequency=True"
    assert suggestions[0]["count"] == 1


def test_low_frequency_excluded_by_default(tmp_path: Path):
    """Without include_low_frequency, singletons are excluded."""
    from finance_etl.merchant_rules import analyze_descriptions

    _client, db_path = _make_client(tmp_path)

    _seed_transactions_with_desc(db_path, [
        ("fp1", "UNIQUE COFFEE SHOP PORTLAND OR", None, -5.00),
    ])

    conn = get_connection(db_path, read_only=True)
    suggestions = analyze_descriptions(conn, min_transactions=3)
    conn.close()

    assert len(suggestions) == 0, "Singleton should NOT appear without include_low_frequency"
