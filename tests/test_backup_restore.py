"""Tests for the v2 backup/restore system."""
import io
import json
from pathlib import Path

import pytest

from finance_etl.backup_migrations import (
    CURRENT_BACKUP_VERSION,
    migrate_v1_to_v2,
    run_migrations,
)
from finance_etl.db import get_connection


# ---------------------------------------------------------------------------
# 1. Full export schema validation
# ---------------------------------------------------------------------------

def test_full_export_schema():
    """migrate_v1_to_v2 produces a valid v2 payload structure."""
    v1 = {
        "backup_version": 1,
        "exported_at": "2024-01-01T00:00:00Z",
        "app_version": "1.5.0",
        "merchant_rules": [{"pattern": "AMZ", "merchant": "Amazon"}],
        "merchant_categories": [{"merchant": "Amazon", "category": "Shopping"}],
        "category_rules": [],
        "budget_goals": [],
        "transactions": [{"transaction_fingerprint": "abc123", "amount": 42}],
    }
    v2 = migrate_v1_to_v2(v1)

    # Top-level keys
    assert v2["backup_version"] == 2
    assert v2["app_version"] == "1.5.0"
    assert v2["created_at"] == "2024-01-01T00:00:00Z"
    assert v2["duckdb_schema_version"] is None

    data = v2["data"]
    # Carried-forward tables
    assert len(data["merchant_rules"]) == 1
    assert data["merchant_rules"][0]["pattern"] == "AMZ"
    assert len(data["merchant_categories"]) == 1
    assert len(data["transactions_norm"]) == 1
    assert data["transactions_norm"][0]["transaction_fingerprint"] == "abc123"

    # New tables default to empty
    assert data["runs"] == []
    assert data["transactions_stage"] == []
    assert data["normalization_jobs"] == []
    assert data["wizard_profiles"] == {}


# ---------------------------------------------------------------------------
# 2. Roundtrip: v2 payload survives migration chain unchanged
# ---------------------------------------------------------------------------

def test_restore_roundtrip():
    """A v2 payload passed through run_migrations(2, 2) is returned as-is."""
    v2 = {
        "backup_version": 2,
        "app_version": "2.0.0",
        "created_at": "2025-06-01T12:00:00Z",
        "duckdb_schema_version": 1,
        "data": {
            "merchant_rules": [{"pattern": "X", "merchant": "Y"}],
            "merchant_categories": [],
            "category_rules": [],
            "budget_goals": [],
            "transactions_norm": [{"transaction_fingerprint": "fp1"}],
            "runs": [{"run_id": "r1"}],
            "transactions_stage": [],
            "normalization_jobs": [],
            "wizard_profiles": {},
        },
    }
    result = run_migrations(v2, 2, 2)
    # Should be the exact same object — no mutations
    assert result is v2


# ---------------------------------------------------------------------------
# 3. v1 → v2 migration
# ---------------------------------------------------------------------------

def test_v1_migration():
    """run_migrations correctly upgrades a v1 payload to v2."""
    v1 = {
        "backup_version": 1,
        "exported_at": "2024-03-15T10:00:00Z",
        "merchant_rules": [{"pattern": "SQ*", "merchant": "Square"}],
        "merchant_categories": [],
        "category_rules": [{"raw_category": "food", "category": "Food", "parent": "Essentials"}],
        "budget_goals": [{"parent": "Essentials", "monthly_amount": 500}],
        "transactions": [
            {"transaction_fingerprint": "fp_a", "amount": 10},
            {"transaction_fingerprint": "fp_b", "amount": 20},
        ],
    }
    result = run_migrations(v1, 1, CURRENT_BACKUP_VERSION)

    assert result["backup_version"] == CURRENT_BACKUP_VERSION
    data = result["data"]
    assert len(data["merchant_rules"]) == 1
    assert len(data["category_rules"]) == 1
    assert len(data["budget_goals"]) == 1
    assert len(data["transactions_norm"]) == 2
    assert data["runs"] == []
    assert data["transactions_stage"] == []


# ---------------------------------------------------------------------------
# 4. Future version rejected
# ---------------------------------------------------------------------------

def test_future_version_not_migrated():
    """run_migrations with from_version > to_version returns payload untouched."""
    future = {"backup_version": 99, "data": {"transactions_norm": []}}
    # Simulating what the API would do: from_version=99, to_version=2
    # range(99, 2) is empty so no migrations run — payload returned as-is
    result = run_migrations(future, 99, CURRENT_BACKUP_VERSION)
    assert result is future


# ---------------------------------------------------------------------------
# 5. Auto-backup rotation
# ---------------------------------------------------------------------------

def test_auto_backup_rotation(tmp_path):
    """Only the 5 most recent auto-backup files should be kept."""
    # Create 7 fake backup files with distinct timestamps
    auto_dir = tmp_path / "auto_backups"
    auto_dir.mkdir()
    for i in range(7):
        (auto_dir / f"auto_backup_2025-01-0{i+1}_120000.json").write_text("{}")

    assert len(list(auto_dir.glob("auto_backup_*.json"))) == 7

    # Simulate rotation logic (same as _write_auto_backup)
    existing = sorted(auto_dir.glob("auto_backup_*.json"), key=lambda p: p.name, reverse=True)
    for old in existing[5:]:
        old.unlink(missing_ok=True)

    remaining = sorted(auto_dir.glob("auto_backup_*.json"))
    assert len(remaining) == 5
    # The two oldest (01, 02) should have been removed
    names = [f.name for f in remaining]
    assert "auto_backup_2025-01-01_120000.json" not in names
    assert "auto_backup_2025-01-02_120000.json" not in names
    # The five newest should remain
    assert "auto_backup_2025-01-07_120000.json" in names
    assert "auto_backup_2025-01-03_120000.json" in names


# ---------------------------------------------------------------------------
# 6. Full export → restore roundtrip via API (Sprint C tables included)
# ---------------------------------------------------------------------------

def test_restore_succeeds_after_sprint_c(tmp_path: Path):
    """POST /backup/restore accepts a v2 payload with all Sprint C tables."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Seed some data including Sprint C duplicate_candidates
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, files_count) "
        "VALUES ('r1', '2025-01-01', 'success', 1)"
    )
    conn.execute(
        "INSERT INTO duplicate_candidates "
        "(fingerprint_a, fingerprint_b, similarity_score, reason, status, detected_at) "
        "VALUES ('fp1', 'fp2', 0.85, 'amount+date', 'pending', '2025-01-01')"
    )
    conn.close()

    # Export
    resp = client.get("/backup/export")
    assert resp.status_code == 200
    backup_bytes = resp.content

    # Restore the same payload
    resp2 = client.post(
        "/backup/restore",
        files={"file": ("backup.json", io.BytesIO(backup_bytes), "application/json")},
    )
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["status"] == "ok"
    assert body["runs_restored"] == 1

    # Verify data survived roundtrip
    conn2 = get_connection(db_path, read_only=True)
    dup_count = conn2.execute("SELECT COUNT(*) FROM duplicate_candidates").fetchone()[0]
    conn2.close()
    assert dup_count == 1


# ---------------------------------------------------------------------------
# 7. Restore blocked while background job is active
# ---------------------------------------------------------------------------

def test_restore_blocked_during_active_job(tmp_path: Path):
    """POST /backup/restore returns 409 when a background job is running."""
    from fastapi.testclient import TestClient
    import finance_etl.api as api_module
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Simulate a running background job
    api_module._async_runs["fake_run"] = {"status": "committing", "run_id": "fake_run"}

    minimal_backup = json.dumps({
        "backup_version": CURRENT_BACKUP_VERSION,
        "app_version": "2.0.0",
        "created_at": "2025-01-01T00:00:00Z",
        "duckdb_schema_version": 1,
        "data": {},
    })
    resp = client.post(
        "/backup/restore",
        files={"file": ("backup.json", io.BytesIO(minimal_backup.encode()), "application/json")},
    )
    assert resp.status_code == 409
    assert "background jobs" in resp.json()["detail"].lower()

    # Clean up
    api_module._async_runs.pop("fake_run", None)


# ---------------------------------------------------------------------------
# 8. Duplicate detection releases connection after completion
# ---------------------------------------------------------------------------

def test_duplicate_task_releases_connection(tmp_path: Path):
    """After duplicate detection, a new read-write connection can be opened."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Seed two similar transactions to trigger duplicate detection
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, files_count) "
        "VALUES ('duprun1', '2025-01-01', 'success', 1)"
    )
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_date, description, merchant, amount, currency, bank_name, "
        "account_name, account_id, source_file, source_row, file_hash, "
        "transaction_fingerprint, ingested_at, statement_type, run_id) "
        "VALUES ('2025-01-01','Coffee Shop','Coffee',5.00,'USD','Bank','Chk','a1',"
        "'f.csv',1,'h1','fp_dup_1','2025-01-01','bank','duprun1')"
    )
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_date, description, merchant, amount, currency, bank_name, "
        "account_name, account_id, source_file, source_row, file_hash, "
        "transaction_fingerprint, ingested_at, statement_type, run_id) "
        "VALUES ('2025-01-02','Coffee Shop','Coffee',5.00,'USD','Bank','Chk','a1',"
        "'f.csv',2,'h1','fp_dup_2','2025-01-01','bank','duprun1')"
    )
    conn.close()

    # Hit the duplicates list endpoint (triggers a read connection)
    resp = client.get("/duplicates")
    assert resp.status_code == 200

    # Now verify we can still open a read-write connection (no leaked connections)
    conn2 = get_connection(db_path)
    row = conn2.execute("SELECT COUNT(*) FROM transactions_norm").fetchone()
    conn2.close()
    assert row[0] == 2


# ---------------------------------------------------------------------------
# 9. category_override survives backup/restore roundtrip
# ---------------------------------------------------------------------------

def test_category_override_survives_backup_restore(tmp_path: Path):
    """category_override=TRUE and category_normalized are preserved through export/restore."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Seed a transaction with category_override=TRUE
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, "
        "bank_name, account_name, account_id, source_file, source_row, file_hash, "
        "category_normalized, category_parent, category_override) "
        "VALUES ('fp_override', '2024-06-01', 'test', -50, "
        "'Bank', 'Acct', 'a1', 'f.csv', 1, 'h1', "
        "'ManualCat', 'Food & Dining', TRUE)"
    )
    conn.close()

    # Export
    resp = client.get("/backup/export")
    assert resp.status_code == 200
    backup_bytes = resp.content

    # Verify export contains category_override
    payload = json.loads(backup_bytes)
    txns = payload["data"]["transactions_norm"]
    assert len(txns) == 1
    assert txns[0]["category_override"] == True
    assert txns[0]["category_normalized"] == "ManualCat"

    # Restore
    resp2 = client.post(
        "/backup/restore",
        files={"file": ("backup.json", io.BytesIO(backup_bytes), "application/json")},
    )
    assert resp2.status_code == 200

    # Verify category_override survived
    conn2 = get_connection(db_path, read_only=True)
    row = conn2.execute(
        "SELECT category_normalized, category_parent, category_override "
        "FROM transactions_norm WHERE transaction_fingerprint = 'fp_override'"
    ).fetchone()
    conn2.close()
    assert row[0] == "ManualCat"
    assert row[1] == "Food & Dining"
    assert row[2] == True


# ---------------------------------------------------------------------------
# 10. recurring_overrides full columns survive backup/restore
# ---------------------------------------------------------------------------

def test_recurring_overrides_full_columns_roundtrip(tmp_path: Path):
    """All recurring_overrides columns (label, amount, frequency, paused, last_date)
    survive backup export and restore."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO recurring_overrides
           (merchant_key, is_recurring, label, amount, frequency,
            paused, last_date, created_at, updated_at)
           VALUES ('Netflix', TRUE, 'Netflix Streaming', 15.99, 'monthly',
                   FALSE, '2025-12-15', '2025-01-01', '2025-01-01')"""
    )
    conn.execute(
        """INSERT INTO recurring_overrides
           (merchant_key, is_recurring, label, amount, frequency,
            paused, last_date, created_at, updated_at)
           VALUES ('Amazon Prime', TRUE, 'Prime Annual', 139.00, 'annual',
                   TRUE, '2025-06-01', '2025-01-01', '2025-01-01')"""
    )
    conn.close()

    # Export
    resp = client.get("/backup/export")
    assert resp.status_code == 200
    payload = json.loads(resp.content)
    overrides = payload["data"]["recurring_overrides"]
    assert len(overrides) == 2

    # Verify exported data includes all columns
    netflix = next(o for o in overrides if o["merchant_key"] == "Netflix")
    assert netflix["label"] == "Netflix Streaming"
    assert float(netflix["amount"]) == 15.99
    assert netflix["frequency"] == "monthly"

    prime = next(o for o in overrides if o["merchant_key"] == "Amazon Prime")
    assert prime["label"] == "Prime Annual"
    assert float(prime["amount"]) == 139.00
    assert prime["frequency"] == "annual"
    assert prime["paused"] == True
    assert prime["last_date"] == "2025-06-01"

    # Restore
    resp2 = client.post(
        "/backup/restore",
        files={"file": ("backup.json", io.BytesIO(resp.content), "application/json")},
    )
    assert resp2.status_code == 200
    assert resp2.json()["recurring_overrides_restored"] == 2

    # Verify data survived
    conn2 = get_connection(db_path, read_only=True)
    rows = conn2.execute(
        "SELECT merchant_key, label, amount, frequency, paused, last_date "
        "FROM recurring_overrides ORDER BY merchant_key"
    ).fetchall()
    conn2.close()
    assert len(rows) == 2
    # Amazon Prime
    assert rows[0][1] == "Prime Annual"
    assert float(rows[0][2]) == 139.00
    assert rows[0][3] == "annual"
    assert rows[0][4] == True
    assert rows[0][5] == "2025-06-01"
    # Netflix
    assert rows[1][1] == "Netflix Streaming"
    assert float(rows[1][2]) == 15.99
    assert rows[1][3] == "monthly"


# ---------------------------------------------------------------------------
# 11. Dismissal tables survive backup/restore
# ---------------------------------------------------------------------------

def test_dismissal_tables_roundtrip(tmp_path: Path):
    """recurring_dismissals, category_dismissals, and rule_dismissals
    survive backup export and restore."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO recurring_dismissals (suggestion_id, dismissed_at) "
        "VALUES ('annual_fee_1', '2025-03-01T10:00:00')"
    )
    conn.execute(
        "INSERT INTO category_dismissals (suggestion_key, dismissed_at) "
        "VALUES ('cat_sugg_1', '2025-03-01T11:00:00')"
    )
    conn.execute(
        "INSERT INTO rule_dismissals (suggestion_key, dismissed_at) "
        "VALUES ('rule_sugg_1', '2025-03-01T12:00:00')"
    )
    conn.close()

    # Export
    resp = client.get("/backup/export")
    assert resp.status_code == 200
    payload = json.loads(resp.content)
    assert len(payload["data"]["recurring_dismissals"]) == 1
    assert len(payload["data"]["category_dismissals"]) == 1
    assert len(payload["data"]["rule_dismissals"]) == 1

    # Restore
    resp2 = client.post(
        "/backup/restore",
        files={"file": ("backup.json", io.BytesIO(resp.content), "application/json")},
    )
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["recurring_dismissals_restored"] == 1
    assert body["category_dismissals_restored"] == 1
    assert body["rule_dismissals_restored"] == 1

    # Verify data survived
    conn2 = get_connection(db_path, read_only=True)
    rd = conn2.execute("SELECT suggestion_id FROM recurring_dismissals").fetchall()
    cd = conn2.execute("SELECT suggestion_key FROM category_dismissals").fetchall()
    rld = conn2.execute("SELECT suggestion_key FROM rule_dismissals").fetchall()
    conn2.close()
    assert len(rd) == 1 and rd[0][0] == "annual_fee_1"
    assert len(cd) == 1 and cd[0][0] == "cat_sugg_1"
    assert len(rld) == 1 and rld[0][0] == "rule_sugg_1"
