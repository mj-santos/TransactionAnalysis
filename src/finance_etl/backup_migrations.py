"""
Backup payload migration chain.

Transforms older backup formats into the current v2 schema so that
backups created by earlier app versions can be restored without data loss.
"""
from __future__ import annotations

# Current backup format version — bump when the payload schema changes
CURRENT_BACKUP_VERSION = 2


def migrate_v1_to_v2(payload: dict) -> dict:
    """
    v1 backup has top-level keys: merchant_rules, merchant_categories,
    category_rules, budget_goals, transactions.
    v2 wraps everything under a "data" key and adds tables that didn't
    exist in v1 (runs, transactions_stage, normalization_jobs, wizard_profiles).
    """
    data: dict = {}

    # Carry forward the tables that existed in v1
    data["merchant_rules"] = payload.get("merchant_rules", [])
    data["merchant_categories"] = payload.get("merchant_categories", [])
    data["category_rules"] = payload.get("category_rules", [])
    data["budget_goals"] = payload.get("budget_goals", [])
    data["transactions_norm"] = payload.get("transactions", [])

    # Tables not present in v1 — empty defaults
    data["runs"] = []
    data["transactions_stage"] = []
    data["normalization_jobs"] = []
    data["wizard_profiles"] = {}

    return {
        "backup_version": 2,
        "app_version": payload.get("app_version"),
        "created_at": payload.get("exported_at"),
        "duckdb_schema_version": None,
        "data": data,
    }


def run_migrations(payload: dict, from_version: int, to_version: int) -> dict:
    """Run migration chain from from_version up to to_version sequentially."""
    migrations = {
        1: migrate_v1_to_v2,
    }
    for v in range(from_version, to_version):
        if v in migrations:
            payload = migrations[v](payload)
    return payload
