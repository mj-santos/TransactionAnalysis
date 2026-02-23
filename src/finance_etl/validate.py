"""
Stage 6 — Validate.

Validates normalized rows against required field rules.
Produces a JSON report at data/validation/<run_id>.json.
Returns (valid_rows, validation_report).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from finance_etl.utils.log import get_logger

log = get_logger(__name__)

LARGE_TRANSACTION_THRESHOLD = Decimal("10000.00")


def validate_normalized(
    normalized_rows: list[dict],
    prior_errors: list[dict],
    run_id: str,
    validation_dir: Path,
    large_tx_threshold: Decimal = LARGE_TRANSACTION_THRESHOLD,
) -> tuple[list[dict], dict[str, Any]]:
    """
    Validate normalized rows.

    Returns
    -------
    (valid_rows, report_dict)
      valid_rows: rows that pass all critical checks
      report_dict: the full validation report (also saved to disk)
    """
    valid = []
    critical_errors = list(prior_errors)  # carry forward normalization errors
    warnings = []

    for row in normalized_rows:
        row_errors = _check_critical(row)
        if row_errors:
            for e in row_errors:
                critical_errors.append({"source_row": row.get("source_row"), "error": e})
        else:
            valid.append(row)
            row_warnings = _check_warnings(row, large_tx_threshold)
            warnings.extend(
                {"source_row": row.get("source_row"), "warning": w} for w in row_warnings
            )

    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_normalized": len(normalized_rows),
        "rows_valid": len(valid),
        "rows_with_critical_errors": len(critical_errors),
        "rows_with_warnings": len(warnings),
        "critical_errors": critical_errors,
        "warnings": warnings,
    }

    # Save report
    validation_dir.mkdir(parents=True, exist_ok=True)
    report_path = validation_dir / f"{run_id}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(
        "Validation: %d valid, %d errors, %d warnings → %s",
        len(valid), len(critical_errors), len(warnings), report_path
    )

    return valid, report


def _check_critical(row: dict) -> list[str]:
    errors = []

    if not row.get("transaction_date"):
        errors.append("Missing transaction_date")

    desc = row.get("description")
    if not desc or not str(desc).strip():
        errors.append("Missing or empty description")

    amount = row.get("amount")
    if amount is None:
        errors.append("Missing amount")
    else:
        try:
            d = Decimal(str(amount))
            if d != d:  # NaN check
                errors.append("Amount is NaN")
        except Exception:
            errors.append(f"Non-numeric amount: {amount!r}")

    for field in ("bank_name", "account_name", "account_id", "source_file",
                  "file_hash", "transaction_fingerprint"):
        if not row.get(field):
            errors.append(f"Missing required field: {field}")

    return errors


def _check_warnings(row: dict, threshold: Decimal) -> list[str]:
    warnings = []
    amount = row.get("amount")
    if amount is not None:
        try:
            if abs(Decimal(str(amount))) > threshold:
                warnings.append(f"Large transaction: {amount}")
        except Exception:
            pass
    if not row.get("category"):
        warnings.append("Missing category")
    return warnings
