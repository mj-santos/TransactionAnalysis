"""
Amount parsing and normalization.

Canonical rule: outflow = negative, inflow = positive.
Always uses Decimal — never float.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


class AmountParseError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Low-level string → Decimal
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = re.compile(r"[$€£¥₹]")


def _parse_raw(
    raw: str,
    decimal_separator: str = ".",
    thousands_separator: str = ",",
    parentheses_negative: bool = False,
) -> Decimal:
    """
    Parse a raw amount string into a Decimal.
    Signs are preserved; parentheses treated as negative when enabled.
    """
    if not raw or not raw.strip():
        raise AmountParseError(f"Empty amount string: {raw!r}")

    s = raw.strip()

    # Detect parentheses negative BEFORE stripping
    is_paren_negative = False
    if parentheses_negative and s.startswith("(") and s.endswith(")"):
        is_paren_negative = True
        s = s[1:-1].strip()

    # Strip currency symbols
    s = _CURRENCY_SYMBOLS.sub("", s).strip()

    # Remove thousands separator
    if thousands_separator:
        s = s.replace(thousands_separator, "")

    # Normalize decimal separator
    if decimal_separator != ".":
        s = s.replace(decimal_separator, ".")

    # Strip leftover whitespace
    s = s.strip()

    try:
        value = Decimal(s)
    except InvalidOperation:
        raise AmountParseError(f"Cannot parse amount: {raw!r} (cleaned: {s!r})")

    if is_paren_negative:
        value = -abs(value)

    return value


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Family parsers
# ---------------------------------------------------------------------------

def parse_signed(
    signed_raw: str,
    locale_cfg: dict[str, Any] | None = None,
) -> Decimal:
    """Family A: single signed column."""
    cfg = locale_cfg or {}
    raw = _parse_raw(
        signed_raw,
        decimal_separator=cfg.get("decimal_separator", "."),
        thousands_separator=cfg.get("thousands_separator", ","),
        parentheses_negative=cfg.get("parentheses_negative", False),
    )
    return _quantize(raw)


def parse_debit_credit(
    debit_raw: str | None,
    credit_raw: str | None,
    locale_cfg: dict[str, Any] | None = None,
) -> Decimal:
    """
    Family B: debit_col and credit_col.
    Exactly one should be non-empty.  If both populated, raise.
    """
    cfg = locale_cfg or {}
    kwargs = dict(
        decimal_separator=cfg.get("decimal_separator", "."),
        thousands_separator=cfg.get("thousands_separator", ","),
        parentheses_negative=cfg.get("parentheses_negative", False),
    )

    has_debit = bool(debit_raw and debit_raw.strip())
    has_credit = bool(credit_raw and credit_raw.strip())

    if has_debit and has_credit:
        raise AmountParseError(
            f"Both debit ({debit_raw!r}) and credit ({credit_raw!r}) are populated. "
            "This bank format is not supported without explicit config."
        )
    if not has_debit and not has_credit:
        raise AmountParseError("Both debit and credit columns are empty.")

    if has_debit:
        return _quantize(-abs(_parse_raw(debit_raw, **kwargs)))
    else:
        return _quantize(abs(_parse_raw(credit_raw, **kwargs)))


def parse_money_in_out(
    money_in_raw: str | None,
    money_out_raw: str | None,
    locale_cfg: dict[str, Any] | None = None,
) -> Decimal:
    """Family C: money_in and money_out columns."""
    cfg = locale_cfg or {}
    kwargs = dict(
        decimal_separator=cfg.get("decimal_separator", "."),
        thousands_separator=cfg.get("thousands_separator", ","),
        parentheses_negative=cfg.get("parentheses_negative", False),
    )

    money_in = Decimal("0")
    money_out = Decimal("0")

    if money_in_raw and money_in_raw.strip():
        money_in = abs(_parse_raw(money_in_raw, **kwargs))
    if money_out_raw and money_out_raw.strip():
        money_out = abs(_parse_raw(money_out_raw, **kwargs))

    if money_in == 0 and money_out == 0:
        raise AmountParseError("Both money_in and money_out are empty or zero.")

    return _quantize(money_in - money_out)


def parse_amount_plus_flag(
    amount_raw: str,
    dc_flag_raw: str,
    debit_values: list[str],
    credit_values: list[str],
    locale_cfg: dict[str, Any] | None = None,
) -> Decimal:
    """Family D: amount column + debit/credit flag column."""
    cfg = locale_cfg or {}
    kwargs = dict(
        decimal_separator=cfg.get("decimal_separator", "."),
        thousands_separator=cfg.get("thousands_separator", ","),
        parentheses_negative=cfg.get("parentheses_negative", False),
    )

    value = abs(_parse_raw(amount_raw, **kwargs))
    flag = (dc_flag_raw or "").strip()

    if flag in debit_values:
        return _quantize(-value)
    elif flag in credit_values:
        return _quantize(value)
    else:
        raise AmountParseError(
            f"Unknown dc_flag value {flag!r}. "
            f"Expected one of debit={debit_values} or credit={credit_values}."
        )
