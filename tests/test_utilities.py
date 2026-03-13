"""Tests for the Utilities endpoints."""
from pathlib import Path

from finance_etl.db import get_connection


def test_health_per_type_breakdown(tmp_path: Path):
    """GET /utilities/health returns per_type breakdown by statement_type."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    # Insert CC transaction (uncategorized, unreviewed)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, "
        "bank_name, account_name, account_id, source_file, source_row, file_hash, "
        "statement_type, unreviewed) "
        "VALUES ('fp_cc1', '2025-01-01', 'test cc', -10, "
        "'Bank', 'CC', 'a1', 'f.csv', 1, 'h1', 'credit_card', TRUE)"
    )
    # Insert bank transaction (uncategorized, unreviewed, no merchant)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, "
        "bank_name, account_name, account_id, source_file, source_row, file_hash, "
        "statement_type, unreviewed) "
        "VALUES ('fp_bk1', '2025-01-01', 'test bank', -20, "
        "'Bank', 'Chk', 'a2', 'f.csv', 2, 'h2', 'bank', TRUE)"
    )
    conn.close()

    resp = client.get("/utilities/health")
    assert resp.status_code == 200
    body = resp.json()

    assert "per_type" in body
    pt = body["per_type"]
    assert "credit_card" in pt
    assert "bank" in pt
    assert pt["credit_card"]["uncategorized"] == 1
    assert pt["bank"]["uncategorized"] == 1
    assert pt["credit_card"]["unreviewed"] == 1
    assert pt["bank"]["unreviewed"] == 1


def test_health_does_not_include_merchants_without_category(tmp_path: Path):
    """Health endpoint no longer returns 'merchants_without_category' metric."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    # Initialize the database schema
    conn = get_connection(db_path)
    conn.close()

    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    resp = client.get("/utilities/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "merchants_without_category" not in body


def test_category_list_returns_200(tmp_path: Path):
    """GET /utilities/categories returns 200 with built-in taxonomy entries."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app
    from finance_etl.category_rules import BUILT_IN_CATEGORY_MAP

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Bootstrap DB schema by opening a read-write connection
    conn = get_connection(db_path)
    conn.close()

    resp = client.get("/utilities/categories")
    assert resp.status_code == 200, f"Response: {resp.json()}"

    body = resp.json()
    assert "categories" in body
    categories = body["categories"]

    # Should have at least one parent group from the built-in taxonomy
    assert len(categories) > 0

    # Collect all unique parent names from the built-in map
    expected_parents = {parent for _, (_, parent) in BUILT_IN_CATEGORY_MAP.items()}

    returned_parents = {c["parent"] for c in categories}
    # Every built-in parent should appear in the response
    assert expected_parents.issubset(returned_parents), (
        f"Missing parents: {expected_parents - returned_parents}"
    )

    # Each entry has the correct shape
    for entry in categories:
        assert "parent" in entry
        assert "count" in entry
        assert "subcategories" in entry
        assert isinstance(entry["count"], int)
        for sub in entry["subcategories"]:
            assert "name" in sub
            assert "count" in sub
