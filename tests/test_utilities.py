"""Tests for the Utilities endpoints."""
from pathlib import Path

from finance_etl.db import get_connection


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
