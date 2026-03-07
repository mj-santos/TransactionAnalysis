"""
Stage 5 — Normalize.

Reads staged rows for a run_id and produces normalized dicts
ready for validation + loading.

All amount/date/text normalization happens here in Python (not SQL)
for full determinism and auditability.

Credit-card rows are classified into spending / payment / adjustment
using one of three formats:

  Format C (two_col):
    cc_charge populated, cc_payment empty  → spending
    cc_payment populated, cc_charge empty  → payment
    Both populated on same row             → conflict (flagged, not committed)

  Format A (single_col, positive = spending):
    Amount > 0  → spending,    resolved_amount = Amount
    Amount < 0  → payment,     resolved_amount = abs(Amount)
    Amount = 0  → adjustment,  resolved_amount = 0 (log warning)

  Format B (single_col, positive = payment):
    Amount > 0  → payment,     resolved_amount = Amount
    Amount < 0  → spending,    resolved_amount = abs(Amount)
    Amount = 0  → adjustment,  resolved_amount = 0 (log warning)

  Refund override: description matches REFUND_KEYWORDS → adjustment (all formats).

resolved_amount is ALWAYS stored as a positive Decimal >= 0.
Sign direction is encoded entirely in transaction_subtype.
Bank rows: transaction_subtype = None, resolved_amount = None.
"""
from __future__ import annotations

import datetime
import json
import re
from decimal import Decimal
from typing import Any

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.merchant_rules import apply_rules, learn_category, load_category_map, load_rules
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


# Refund/chargeback keywords — description containing any of these overrides
# the subtype to 'adjustment' regardless of sign or format.
REFUND_KEYWORDS: frozenset[str] = frozenset({
    "refund", "reversal", "chargeback", "credit adj", "creditadj",
    "promotional credit", "fee reversal", "return credit",
})


def _description_is_refund(description: str) -> bool:
    """Return True if description text matches a refund/chargeback keyword."""
    desc_lower = description.lower()
    return any(kw in desc_lower for kw in REFUND_KEYWORDS)


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
    amount_cfg = mapping.get("amount", {})

    # CC-specific format info (set by wizard_to_pipeline_mapping)
    cc_format   = amount_cfg.get("cc_format")    # 'two_col' | 'single_col' | None
    cc_polarity = amount_cfg.get("cc_polarity")  # 'format_a' | 'format_b' | None

    rows = conn.execute(
        "SELECT * FROM transactions_stage WHERE run_id = ?", [run_id]
    ).fetchall()

    col_names = [d[0] for d in conn.description]

    # Load merchant rules and category map once for the whole batch
    rules = load_rules(conn)
    cat_map = load_category_map(conn)

    normalized = []
    errors = []
    to_learn: list[tuple[str, str]] = []  # (merchant, category) pairs to persist

    for raw in rows:
        row = dict(zip(col_names, raw))
        try:
            norm = _normalize_row(
                row, family, locale_cfg, date_format, dc_flag_values,
                statement_type, cc_format, cc_polarity,
            )

            # Apply merchant normalization rules to description
            matched_merchant = apply_rules(norm["description"], rules)
            if matched_merchant is not None:
                norm["merchant"] = matched_merchant
            # If no rule matched, keep whatever came through from extra_json

            # Resolve category from merchant_category_map
            merchant_key = (norm.get("merchant") or "").lower()
            if merchant_key and norm.get("category") is None:
                resolved_cat = cat_map.get(merchant_key)
                if resolved_cat:
                    norm["category"] = resolved_cat

            # Collect (merchant, category) pairs for learned category writing
            if norm.get("merchant") and norm.get("category"):
                cat_source = cat_map.get(norm["merchant"].lower())
                # Only learn if not already user-assigned
                if cat_source is None:
                    to_learn.append((norm["merchant"], norm["category"]))

            normalized.append(norm)
        except (NormalizationError, AmountParseError, DateParseError) as e:
            errors.append({"source_row": row.get("source_row"), "error": str(e)})
            log.warning("Row %s normalization error: %s", row.get("source_row"), e)

    # Write learned categories (deduped) — never overwrites user-assigned entries
    seen_learn: set[str] = set()
    for merchant, category in to_learn:
        key = merchant.lower()
        if key not in seen_learn:
            seen_learn.add(key)
            try:
                learn_category(conn, merchant, category)
            except Exception as exc:
                log.warning("Failed to learn category for %r: %s", merchant, exc)

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
    cc_format: str | None = None,
    cc_polarity: str | None = None,
) -> dict:
    # --- Amount + CC subtype classification ---
    is_cc = (statement_type == "credit_card")

    if is_cc:
        amount, transaction_subtype, resolved_amount = _classify_cc_row(
            row, family, locale_cfg, cc_format, cc_polarity,
        )
    else:
        amount = resolve_amount(row, family, locale_cfg, dc_flag_values)
        transaction_subtype = None
        resolved_amount = None

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

    # --- Refund override for CC rows ---
    if is_cc and transaction_subtype not in ("conflict", None):
        if _description_is_refund(description):
            transaction_subtype = "adjustment"
            resolved_amount = abs(resolved_amount) if resolved_amount is not None else Decimal(0)
            log.debug(
                "Refund keyword override at source_row=%s: subtype → adjustment",
                row.get("source_row"),
            )

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
        # CC subtype model
        "transaction_subtype": transaction_subtype,
        "resolved_amount": resolved_amount,
    }


# ---------------------------------------------------------------------------
# Credit-card subtype classification
# ---------------------------------------------------------------------------

def _classify_cc_row(
    row: dict,
    family: str,
    locale_cfg: dict,
    cc_format: str | None,
    cc_polarity: str | None,
) -> tuple[Decimal, str | None, Decimal | None]:
    """
    Classify a credit-card row into spending / payment / adjustment / conflict.

    Returns (amount, transaction_subtype, resolved_amount).

    amount         — the signed amount used for fingerprinting (existing semantics)
    transaction_subtype — 'spending' | 'payment' | 'adjustment' | 'conflict' | None
    resolved_amount — always >= 0; direction encoded in transaction_subtype
    """
    if cc_format == "two_col":
        return _classify_two_col(row, locale_cfg)
    else:
        # Single-column (Format A or B), or unknown cc_format
        return _classify_single_col(row, family, locale_cfg, cc_polarity)


def _classify_two_col(
    row: dict,
    locale_cfg: dict,
) -> tuple[Decimal, str, Decimal]:
    """
    Format C — two-column (cc_charge / cc_payment mapped to debit_raw / credit_raw).

    cc_charge → debit_raw (spending)
    cc_payment → credit_raw (payment)
    Both populated → conflict
    """
    charge_raw  = (row.get("debit_raw")  or "").strip()
    payment_raw = (row.get("credit_raw") or "").strip()

    has_charge  = bool(charge_raw)
    has_payment = bool(payment_raw)

    if has_charge and has_payment:
        # Conflict — cannot auto-split; flag for user resolution
        # Use charge amount as the stored amount for fingerprinting (arbitrary but consistent)
        try:
            charge_val = parse_signed(charge_raw, locale_cfg)
        except AmountParseError:
            charge_val = Decimal(0)
        log.warning(
            "CC conflict row at source_row=%s: both cc_charge=%r and cc_payment=%r populated",
            row.get("source_row"), charge_raw, payment_raw,
        )
        return (charge_val, "conflict", abs(charge_val))

    if has_charge:
        try:
            charge_val = parse_signed(charge_raw, locale_cfg)
            resolved = abs(charge_val)
        except AmountParseError as exc:
            raise NormalizationError(
                f"Cannot parse cc_charge={charge_raw!r} at source_row={row.get('source_row')}: {exc}"
            ) from exc
        # Store as negative for backward compat (spending = outflow from user perspective)
        return (-resolved, "spending", resolved)

    if has_payment:
        try:
            payment_val = parse_signed(payment_raw, locale_cfg)
            resolved = abs(payment_val)
        except AmountParseError as exc:
            raise NormalizationError(
                f"Cannot parse cc_payment={payment_raw!r} at source_row={row.get('source_row')}: {exc}"
            ) from exc
        # Store as positive (payment = inflow to card balance)
        return (resolved, "payment", resolved)

    # Both empty — no amount data
    raise NormalizationError(
        f"CC row has no amount data (cc_charge and cc_payment both empty) "
        f"at source_row={row.get('source_row')}"
    )


def _classify_single_col(
    row: dict,
    family: str,
    locale_cfg: dict,
    cc_polarity: str | None,
) -> tuple[Decimal, str | None, Decimal | None]:
    """
    Format A / B — single amount column.

    cc_polarity='format_a': positive → spending, negative → payment
    cc_polarity='format_b': positive → payment,  negative → spending

    If cc_polarity is not set, falls through to the legacy signed resolver
    (no subtype is assigned).
    """
    amount_raw = (row.get("amount_raw") or "").strip()
    if not amount_raw:
        raise NormalizationError(
            f"CC single-col row has no amount data at source_row={row.get('source_row')}"
        )

    try:
        value = parse_signed(amount_raw, locale_cfg)
    except AmountParseError as exc:
        raise NormalizationError(
            f"Cannot parse cc_amount={amount_raw!r} at source_row={row.get('source_row')}: {exc}"
        ) from exc

    resolved = abs(value)

    if value == Decimal(0):
        # Zero amount → adjustment (log warning)
        log.warning(
            "CC zero-amount row at source_row=%s; assigned subtype=adjustment",
            row.get("source_row"),
        )
        return (Decimal(0), "adjustment", Decimal(0))

    if cc_polarity == "format_a":
        # Positive = spending (most US cards)
        if value > 0:
            return (-resolved, "spending", resolved)
        else:
            return (resolved, "payment", resolved)

    if cc_polarity == "format_b":
        # Positive = payment (some EU/UK banks)
        if value > 0:
            return (resolved, "payment", resolved)
        else:
            return (-resolved, "spending", resolved)

    # No polarity confirmed — return raw amount with no subtype
    return (value, None, None)


# ---------------------------------------------------------------------------
# Legacy resolve_amount (used by bank rows)
# ---------------------------------------------------------------------------

def resolve_amount(
    row: dict,
    family: str,
    locale_cfg: dict,
    dc_flag_values: dict,
) -> Decimal:
    """
    Priority-based amount resolution for bank rows.

    Step 1 — Try the mapped amount_format_family (backward-compatible).
    Step 2 — All empty → NormalizationError; row is skipped and logged.
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

    # Step 2: fallback to amount_debit_raw / amount_credit_raw (cc_charge/cc_payment staging cols)
    debit_raw = (row.get("amount_debit_raw") or "").strip()
    credit_raw = (row.get("amount_credit_raw") or "").strip()
    if debit_raw or credit_raw:
        debit_val = parse_signed(debit_raw, locale_cfg) if debit_raw else Decimal("0")
        credit_val = parse_signed(credit_raw, locale_cfg) if credit_raw else Decimal("0")
        return credit_val - debit_val

    # Step 3: nothing available — skip row with warning
    src = row.get("source_row", "?")
    src_file = row.get("source_file", "?")
    raise NormalizationError(
        f"No amount data at source_row={src} (file={src_file!r})"
    )
