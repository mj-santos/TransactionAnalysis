"""Tests for dashboard-related endpoints including version and tab routing."""

import re
from pathlib import Path

from finance_etl.db import get_connection


# ---------------------------------------------------------------------------
# resolveTransactionTab logic (mirrors the JS function in app.js)
# ---------------------------------------------------------------------------

def _resolve_transaction_tab(transactions):
    """Python equivalent of resolveTransactionTab() in app.js."""
    cc = sum(1 for t in transactions if t.get("statement_type") == "credit_card")
    bank = sum(1 for t in transactions if t.get("statement_type") == "bank")
    if cc > 0 and bank == 0:
        return "credit_card"
    if bank > 0 and cc == 0:
        return "bank"
    return "credit_card" if cc >= bank else "bank"


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


# ---------------------------------------------------------------------------
# resolveTransactionTab tests — mirrors JS logic for tab routing
# ---------------------------------------------------------------------------

def test_resolve_tab_cc_only():
    """All transactions are credit_card → route to credit_card."""
    txns = [{"statement_type": "credit_card"} for _ in range(5)]
    assert _resolve_transaction_tab(txns) == "credit_card"


def test_resolve_tab_bank_only():
    """All transactions are bank → route to bank."""
    txns = [{"statement_type": "bank"} for _ in range(5)]
    assert _resolve_transaction_tab(txns) == "bank"


def test_resolve_tab_mixed_majority_cc():
    """7 CC + 3 bank → route to credit_card (majority)."""
    txns = ([{"statement_type": "credit_card"}] * 7 +
            [{"statement_type": "bank"}] * 3)
    assert _resolve_transaction_tab(txns) == "credit_card"


def test_resolve_tab_mixed_majority_bank():
    """3 CC + 7 bank → route to bank (majority)."""
    txns = ([{"statement_type": "credit_card"}] * 3 +
            [{"statement_type": "bank"}] * 7)
    assert _resolve_transaction_tab(txns) == "bank"


def test_resolve_tab_tie_defaults_credit_card():
    """5 CC + 5 bank → tie defaults to credit_card."""
    txns = ([{"statement_type": "credit_card"}] * 5 +
            [{"statement_type": "bank"}] * 5)
    assert _resolve_transaction_tab(txns) == "credit_card"
