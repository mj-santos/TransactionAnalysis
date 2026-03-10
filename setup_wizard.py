#!/usr/bin/env python3
"""
Finance ETL — First-Run Setup Wizard
=====================================

Transforms the tool from a manual, data-engineer setup to an automated,
reviewer-focused experience.

Wizard flow
-----------
1. Scan the ``raw_data/`` folder for a bank CSV export.
2. Infer column → canonical-field mapping (header_inference).
3. Cluster transaction descriptions into suggested categories (category_suggestion).
4. Identify high-frequency vendors and auto-generate mapping rules (mapping_rules).
5. Assemble a complete ``config.yaml`` and preview it for the user.
6. Prompt for confirmation before writing to ``config/mappings/<bank_key>.yaml``.

Usage
-----
    python setup_wizard.py                          # interactive
    python setup_wizard.py --yes                    # accept all suggestions
    python setup_wizard.py --raw-data-dir exports/  # custom CSV directory
    python setup_wizard.py --output-config my.yaml  # custom output path

Alternatively, if the package is installed:
    finance_etl wizard --raw-data-dir exports/ --yes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the src/ tree is importable when running without `pip install -e .`
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.resolve()
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from finance_etl.wizard.setup_wizard import run_wizard  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="setup_wizard.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--raw-data-dir",
        default="raw_data",
        metavar="PATH",
        help="Directory to scan for a bank CSV (default: raw_data/)",
    )
    p.add_argument(
        "--output-config",
        default=None,
        metavar="PATH",
        help="Destination path for the generated config.yaml",
    )
    p.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Accept all suggestions automatically without interactive prompts",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        run_wizard(
            raw_data_dir=args.raw_data_dir,
            output_config=args.output_config,
            auto_yes=args.yes,
        )
        sys.exit(0)
    except FileNotFoundError as exc:
        print(f"\n[error] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[wizard] Aborted by user.", file=sys.stderr)
        sys.exit(1)
