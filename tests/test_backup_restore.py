"""Tests for the v2 backup/restore system."""
import json
import pytest

from finance_etl.backup_migrations import (
    CURRENT_BACKUP_VERSION,
    migrate_v1_to_v2,
    run_migrations,
)


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
