"""Tests for dashboard-related endpoints including version."""

import re
from pathlib import Path

from finance_etl.db import get_connection


def _make_client(tmp_path):
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    return TestClient(app), db_path


# ---------------------------------------------------------------------------
# Version endpoint tests
# ---------------------------------------------------------------------------

def test_version_endpoint_reads_from_pyproject_toml(tmp_path: Path):
    """GET /version must return the same version as importlib.metadata reads."""
    from importlib.metadata import version as pkg_version

    client, _ = _make_client(tmp_path)
    resp = client.get("/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == pkg_version("finance_etl")


def test_version_endpoint_format(tmp_path: Path):
    """GET /version must return a valid semantic version string."""
    client, _ = _make_client(tmp_path)
    resp = client.get("/version")
    assert resp.status_code == 200
    version = resp.json()["version"]
    assert version is not None
    assert version != ""
    assert re.match(r"^\d+\.\d+\.\d+", version), (
        f"Version '{version}' does not match semantic version pattern"
    )
