"""Accounts & Liabilities module — FastAPI sub-router."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# Import route modules to register endpoints
from . import routes  # noqa: F401, E402
from . import plaid_stubs  # noqa: F401, E402
