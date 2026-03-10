#!/usr/bin/env python3
"""
Local dev server launcher — no install required.

Adds src/ to sys.path so finance_etl is importable directly from the repo,
then starts the API on port 8000.

Usage:
    python3 run_dev.py
    python3 run_dev.py --port 8001
"""
import sys
from pathlib import Path

# Make the package importable without pip install
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Ensure local data + config directories exist before uvicorn starts
for d in [
    "data/db", "data/raw", "data/uploads",
    "data/reports", "data/master",
    "data/profiles", "data/validation", "data/logs",
    "config/mappings",
]:
    Path(d).mkdir(parents=True, exist_ok=True)

from finance_etl.cli import main  # noqa: E402

if __name__ == "__main__":
    # Forward any extra args; default to local-friendly settings
    args = sys.argv[1:] or []
    sys.argv = ["finance_etl", "api", "--host", "0.0.0.0", "--port", "8000"] + args
    main()
