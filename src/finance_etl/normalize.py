"""
Stage 5 — Normalize.

Reads staged rows for a run_id and produces normalized dicts
ready for validation + loading.

All amount/date/text normalization happens here in Python (not SQL)
for full determinism and auditability.
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.utils.dates import parse_date, DateParseError
from finance_etl.utils.fingerprint import compute_fingerprint
from finance_etl.utils.money import (
    AmountParseError,
    parse_signed,
    parse_debit_credit,
    parse_money_in_out,
    parse_amount_plus_flag,
)
from finance_etl.utils.text import normalize_description
from finance_etl.utils.log import get_logger

log = get_logger(__name__)


class NormalizationError(ValueError):
    pass


def normalize_staged_rows(
    conn,
    run_id: str,
    mapping: dict[str, Any],
    statement_type: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Normalize all staged rows for a run.

    Returns (normalized_rows, errors)
      - normalized_rows: list of dicts ready for load
      - errors: list of {"source_row": int, "error": str}

    statement_type is threaded through to every normalized row so that
    transactions_norm.statement_type is populated for credit_card / bank isolation.
    """
    family = mapping["amount_format_family"]
    locale_cfg = mapping.get("locale", {})
    date_format = mapping.get("date", {}).get("date_format")
    dc_flag_values = mapping.get("amount", {}).get("dc_flag_values", {})

    rows = conn.execute(
        "SELECT * FROM transactions_stage WHERE run_id = ?", [run_id]
    ).fetchall()

    col_names = [d[0] for d in conn.description]

    normalized = []
    errors = []

    for raw in rows:
        row = dict(zip(col_names, raw))
        try:
            norm = _normalize_row(row, family, locale_cfg, date_format, dc_flag_values, statement_type)
            normalized.append(norm)
        except (NormalizationError, AmountParseError, DateParseError) as e:
            errors.append({"source_row": row.get("source_row"), "error": str(e)})
            log.warning("Row %s normalization error: %s", row.get("source_row"), e)

    log.info(
        "Normalization: %d ok, %d errors (run=%s)",
        len(normalized), len(errors), run_id
    )
    return normalized, errors


def _normalize_row(
    row: dict,
    family: str,
    locale_cfg: dict,
    date_format: str | None,
    dc_flag_values: dict,
    statement_type: str | None = None,
) -> dict:
    # --- Amount (Feature 2: priority-based resolution) ---
    amount = resolve_amount(row, family, locale_cfg, dc_flag_values)

    # --- Dates ---
    tx_date = parse_date(row["transaction_date_raw"], date_format=date_format, locale_cfg=locale_cfg)
    posted_date: datetime.date | None = None
    if row.get("posted_date_raw"):
        try:
            posted_date = parse_date(
                row["posted_date_raw"], date_format=date_format, locale_cfg=locale_cfg
            )
        except DateParseError:
            posted_date = None  # posted_date is optional

    # --- Description ---
    description = normalize_description(row.get("description_raw") or "")
    if not description:
        raise NormalizationError(f"Empty description at source_row={row.get('source_row')}")

    # --- Currency ---
    currency = (row.get("currency_raw") or "USD").strip().upper() or "USD"

    # --- Merchant / Category (carried through extra_json by mapping stage) ---
    _extra = json.loads(row.get("extra_json") or "{}")
    merchant = (_extra.get("merchant") or "").strip() or None
    category = (_extra.get("category") or "").strip() or None

    # --- Fingerprint ---
    fingerprint = compute_fingerprint(
        bank_name=row["bank_name"],
        account_id=row["account_id"],
        transaction_date=tx_date,
        description=description,
        amount=amount,
        currency=currency,
    )

    return {
        "transaction_date": tx_date,
        "posted_date": posted_date,
        "description": description,
        "merchant": merchant,
        "category": category,
        "amount": amount,
        "currency": currency,
        "bank_name": row["bank_name"],
        "account_name": row["account_name"],
        "account_id": row["account_id"],
        "source_file": row["source_file"],
        "source_row": row["source_row"],
        "file_hash": row["file_hash"],
        "transaction_fingerprint": fingerprint,
        # Feature 1: classify every row so bank ≠ credit_card is never mixed
        "statement_type": statement_type,
    }


def resolve_amount(
    row: dict,
    family: str,
    locale_cfg: dict,
    dc_flag_values: dict,
) -> Decimal:
    """
    Feature 2: Priority-based amount resolution.

    Step 1 — Try the mapped amount_format_family (backward-compatible).
    Step 2 — Fall back to amount_debit_raw / amount_credit_raw canonical fields
              (result: credit − debit; positive = inflow, negative = outflow).
    Step 3 — All empty → NormalizationError; row is skipped and logged.
    """
    # Step 1: existing family-based parsing
    if family == "signed" and (row.get("amount_raw") or "").strip():
        return parse_signed(row["amount_raw"], locale_cfg)
    elif family == "debit_credit":
        if (row.get("debit_raw") or "").strip() or (row.get("credit_raw") or "").strip():
            return parse_debit_credit(
                row.get("debit_raw", ""), row.get("credit_raw", ""), locale_cfg
            )
    elif family == "money_in_out":
        if (row.get("money_in_raw") or "").strip() or (row.get("money_out_raw") or "").strip():
            return parse_money_in_out(
                row.get("money_in_raw", ""), row.get("money_out_raw", ""), locale_cfg
            )
    elif family == "amount_plus_flag":
        if (row.get("amount_raw") or "").strip():
            return parse_amount_plus_flag(
                row["amount_raw"],
                row.get("dc_flag_raw", ""),
                debit_values=dc_flag_values.get("debit", []),
                credit_values=dc_flag_values.get("credit", []),
                locale_cfg=locale_cfg,
            )

    # Step 2: fall back to amount_debit / amount_credit canonical fields
    ad = (row.get("amount_debit_raw") or "").strip()
    ac = (row.get("amount_credit_raw") or "").strip()
    if ad or ac:
        # amount_debit = outflow (positive number) → stored negative (credit - debit)
        # amount_credit = inflow (positive number) → stored positive
        try:
            debit = parse_signed(ad, locale_cfg) if ad else Decimal(0)
        except AmountParseError:
            log.warning(
                "Cannot parse amount_debit_raw=%r at source_row=%s; treating as 0",
                ad, row.get("source_row"),
            )
            debit = Decimal(0)
        try:
            credit = parse_signed(ac, locale_cfg) if ac else Decimal(0)
        except AmountParseError:
            log.warning(
                "Cannot parse amount_credit_raw=%r at source_row=%s; treating as 0",
                ac, row.get("source_row"),
            )
            credit = Decimal(0)
        return credit - debit

    # Step 3: nothing available — skip row with warning
    src = row.get("source_row", "?")
    src_file = row.get("source_file", "?")
    raise NormalizationError(
        f"No amount data: amount, amount_debit, and amount_credit all empty "
        f"at source_row={src} (file={src_file!r})"
    )
