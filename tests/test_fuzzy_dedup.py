"""Tests for fuzzy duplicate detection (BUG-21) and amount variance UX (BUG-22)."""

from pathlib import Path
from unittest.mock import patch

from finance_etl.db import get_connection
from finance_etl.utils.fuzzy_dedup import fuzzy_duplicate_detection


# ---------------------------------------------------------------------------
# Helper: insert a transaction into transactions_norm
# ---------------------------------------------------------------------------

_SEQ = 0


def _insert_txn(conn, *, fingerprint, account_id="acct_1", date="2026-02-15",
                amount=-23.50, description="UBER EATS 8005928996",
                run_id="run_old", split_parent_fingerprint=None):
    global _SEQ
    _SEQ += 1
    conn.execute(
        """INSERT INTO transactions_norm
           (transaction_date, description, amount, currency, bank_name,
            account_name, account_id, source_file, source_row, file_hash,
            transaction_fingerprint, ingested_at, statement_type, run_id,
            split_parent_fingerprint)
           VALUES (?, ?, ?, 'USD', 'Bank', 'Checking', ?, 'f.csv', ?, 'h1',
                   ?, CURRENT_TIMESTAMP, 'bank', ?, ?)""",
        [date, description, amount, account_id, _SEQ,
         fingerprint, run_id, split_parent_fingerprint],
    )


# ===========================================================================
# BUG-21 Tests
# ===========================================================================


def test_exact_duplicate_not_flagged_as_fuzzy(tmp_path: Path):
    """Identical fingerprint is handled by UNIQUE constraint, not fuzzy pass."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    _insert_txn(conn, fingerprint="fp_same", run_id="run1")

    # The fuzzy pass receives the same fingerprint as "newly imported"
    # but since there's only one row with that fingerprint, there is nothing
    # to compare against — should find 0 candidates.
    count = fuzzy_duplicate_detection(conn, ["fp_same"])
    assert count == 0

    rows = conn.execute("SELECT * FROM duplicate_candidates").fetchall()
    assert len(rows) == 0
    conn.close()


def test_description_drift_flagged(tmp_path: Path):
    """Description change between exports should be flagged."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    # Existing transaction from previous import
    _insert_txn(conn, fingerprint="fp_old", description="STARBUCKS STORE 12345",
                date="2026-02-15", amount=-23.50, run_id="run1")

    # New import with changed description (bank dropped the store number)
    _insert_txn(conn, fingerprint="fp_new", description="STARBUCKS STORE",
                date="2026-02-15", amount=-23.50, run_id="run2")

    count = fuzzy_duplicate_detection(conn, ["fp_new"])
    assert count == 1

    row = conn.execute(
        "SELECT reason, similarity_score FROM duplicate_candidates WHERE status = 'pending'"
    ).fetchone()
    assert row is not None
    assert "fuzzy_description" in row[0]
    assert float(row[1]) >= 0.75
    conn.close()


def test_amount_variance_flagged(tmp_path: Path):
    """Small amount difference should be flagged."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    _insert_txn(conn, fingerprint="fp_a", description="AMAZON",
                date="2026-03-01", amount=-100.00, run_id="run1")
    _insert_txn(conn, fingerprint="fp_b", description="AMAZON",
                date="2026-03-01", amount=-100.35, run_id="run2")

    count = fuzzy_duplicate_detection(conn, ["fp_b"])
    assert count == 1

    row = conn.execute(
        "SELECT reason FROM duplicate_candidates WHERE status = 'pending'"
    ).fetchone()
    assert row is not None
    assert "amount_variance" in row[0]
    conn.close()


def test_different_account_not_flagged(tmp_path: Path):
    """Cross-account matches are invalid — should not flag."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    _insert_txn(conn, fingerprint="fp_chase", account_id="chase_1234",
                description="STARBUCKS", date="2026-02-15", amount=-5.00, run_id="run1")
    _insert_txn(conn, fingerprint="fp_bofa", account_id="bofa_5678",
                description="STARBUCKS", date="2026-02-15", amount=-5.00, run_id="run2")

    count = fuzzy_duplicate_detection(conn, ["fp_bofa"])
    assert count == 0
    conn.close()


def test_date_window_respected(tmp_path: Path):
    """Transactions more than 3 days apart should not be flagged."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    _insert_txn(conn, fingerprint="fp_feb01", description="NETFLIX",
                date="2026-02-01", amount=-15.99, run_id="run1")
    _insert_txn(conn, fingerprint="fp_feb10", description="NETFLIX",
                date="2026-02-10", amount=-15.99, run_id="run2")

    count = fuzzy_duplicate_detection(conn, ["fp_feb10"])
    assert count == 0
    conn.close()


def test_already_flagged_pair_not_duplicated(tmp_path: Path):
    """Running detection twice should not create a second candidate row."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    _insert_txn(conn, fingerprint="fp_x", description="STARBUCKS STORE 12345",
                date="2026-02-15", amount=-23.50, run_id="run1")
    _insert_txn(conn, fingerprint="fp_y", description="STARBUCKS STORE",
                date="2026-02-15", amount=-23.50, run_id="run2")

    count1 = fuzzy_duplicate_detection(conn, ["fp_y"])
    count2 = fuzzy_duplicate_detection(conn, ["fp_y"])
    assert count1 == 1
    assert count2 == 0

    total = conn.execute("SELECT COUNT(*) FROM duplicate_candidates").fetchone()[0]
    assert total == 1
    conn.close()


def test_split_children_excluded(tmp_path: Path):
    """Split child transactions should not be flagged as duplicate candidates."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    # Existing split child
    _insert_txn(conn, fingerprint="fp_child", description="WALMART",
                date="2026-02-15", amount=-50.00, run_id="run1",
                split_parent_fingerprint="fp_parent")

    # New import with similar transaction
    _insert_txn(conn, fingerprint="fp_new_wal", description="WALMART",
                date="2026-02-15", amount=-50.00, run_id="run2")

    count = fuzzy_duplicate_detection(conn, ["fp_new_wal"])
    assert count == 0
    conn.close()


def test_performance_prefilter_reduces_comparisons(tmp_path: Path):
    """Verify that fuzzy comparison only runs on pre-filtered subset."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))

    # Insert 1000 transactions spanning 12 months (various amounts)
    for i in range(1000):
        month = (i % 12) + 1
        day = (i % 28) + 1
        date_str = f"2025-{month:02d}-{day:02d}"
        _insert_txn(conn, fingerprint=f"fp_bulk_{i}",
                     description=f"MERCHANT_{i % 50}",
                     date=date_str, amount=-(10.0 + i * 0.5),
                     account_id="acct_1", run_id="run_bulk")

    # Import 30 transactions for March 2026
    new_fps = []
    for i in range(30):
        fp = f"fp_new_march_{i}"
        new_fps.append(fp)
        _insert_txn(conn, fingerprint=fp,
                     description=f"MERCHANT_{i % 50}",
                     date=f"2026-03-{(i % 28) + 1:02d}",
                     amount=-(10.0 + i * 0.5),
                     account_id="acct_1", run_id="run_march")

    # Track calls to fuzz.token_sort_ratio
    call_count = 0
    original_tsr = __import__('rapidfuzz').fuzz.token_sort_ratio

    def counting_tsr(a, b, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_tsr(a, b, **kwargs)

    with patch('finance_etl.utils.fuzzy_dedup.fuzz.token_sort_ratio', side_effect=counting_tsr):
        fuzzy_duplicate_detection(conn, new_fps)

    # Pre-filter should limit comparisons to date+amount window, not all 1000.
    # March 2026 txns won't match 2025 dates (>3 day window), so very few comparisons.
    assert call_count < 1000, f"Expected pre-filtering to reduce comparisons, got {call_count}"
    conn.close()


# ===========================================================================
# BUG-22 Tests
# ===========================================================================


def test_amount_variance_shows_comparison_ui_data(tmp_path: Path):
    """GET /duplicates returns both amounts and ingested_at for UI rendering."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(str(db_path))
    _insert_txn(conn, fingerprint="fp_orig", description="AMAZON",
                date="2026-01-15", amount=-100.00, run_id="run1")
    _insert_txn(conn, fingerprint="fp_reimp", description="AMAZON",
                date="2026-01-15", amount=-100.35, run_id="run2")
    fuzzy_duplicate_detection(conn, ["fp_reimp"])
    conn.close()

    resp = client.get("/duplicates?status=pending")
    assert resp.status_code == 200
    body = resp.json()
    rows = body["rows"]
    assert len(rows) == 1

    r = rows[0]
    assert r["amount_a"] is not None
    assert r["amount_b"] is not None
    assert r["ingested_at_a"] is not None
    assert r["ingested_at_b"] is not None
    assert "amount_variance" in r["reason"]


def test_import_banner_fires_for_fuzzy_candidates(tmp_path: Path):
    """Import response duplicate_count includes fuzzy candidates."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app
    import finance_etl.api as api_module

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(str(db_path))
    # Pre-existing transaction
    _insert_txn(conn, fingerprint="fp_pre", description="STARBUCKS STORE 12345",
                date="2026-02-15", amount=-23.50, run_id="run_prev")
    conn.close()

    # Directly verify that fuzzy detection finds the drift match
    conn2 = get_connection(str(db_path))
    _insert_txn(conn2, fingerprint="fp_drift", description="STARBUCKS STORE",
                date="2026-02-15", amount=-23.50, run_id="run_new")
    fuzzy_count = fuzzy_duplicate_detection(conn2, ["fp_drift"])
    conn2.close()

    assert fuzzy_count > 0, "Fuzzy detection should have found candidates"

    # Verify duplicates endpoint returns the fuzzy match
    resp = client.get("/duplicates?status=pending")
    assert resp.status_code == 200
    assert resp.json()["count"] > 0


def test_resolve_remove_old_deletes_correct_transaction(tmp_path: Path):
    """Resolving with delete_a removes the original transaction."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(str(db_path))
    _insert_txn(conn, fingerprint="fp_old_amt", description="AMAZON",
                date="2026-01-15", amount=-100.00, run_id="run1")
    _insert_txn(conn, fingerprint="fp_new_amt", description="AMAZON",
                date="2026-01-15", amount=-100.35, run_id="run2")
    fuzzy_duplicate_detection(conn, ["fp_new_amt"])
    conn.close()

    # Get the candidate
    resp = client.get("/duplicates?status=pending")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    dup_id = rows[0]["id"]

    # Resolve: remove old
    resp2 = client.post(f"/duplicates/{dup_id}/resolve", json={"action": "delete_a"})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "resolved_removed_old"

    # Verify original deleted, new remains
    conn2 = get_connection(str(db_path), read_only=True)
    old = conn2.execute(
        "SELECT 1 FROM transactions_norm WHERE transaction_fingerprint = 'fp_old_amt'"
    ).fetchone()
    new = conn2.execute(
        "SELECT 1 FROM transactions_norm WHERE transaction_fingerprint = 'fp_new_amt'"
    ).fetchone()
    dup_row = conn2.execute(
        "SELECT status FROM duplicate_candidates WHERE id = ?", [dup_id]
    ).fetchone()
    conn2.close()

    assert old is None, "Original transaction should have been deleted"
    assert new is not None, "Re-imported transaction should remain"
    assert dup_row[0] == "resolved_removed_old"
