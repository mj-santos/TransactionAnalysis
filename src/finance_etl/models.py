"""Typed models for config and run ledger guardrails."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AmountFamily = Literal["signed", "debit_credit", "money_in_out", "amount_plus_flag"]


@dataclass(frozen=True)
class DateConfig:
    transaction_date: str
    posted_date: str | None = None
    date_format: str | None = None


@dataclass(frozen=True)
class AmountConfig:
    signed_amount: str | None = None
    debit_col: str | None = None
    credit_col: str | None = None
    money_in_col: str | None = None
    money_out_col: str | None = None
    amount_col: str | None = None
    dc_flag_col: str | None = None
    dc_flag_values: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class MappingConfig:
    bank_key: str
    bank_name: str
    amount_format_family: AmountFamily
    column_map: dict[str, str]
    date: DateConfig
    amount: AmountConfig
    account_name: str = ""
    account_id: str = ""
    drop_columns: list[str] = field(default_factory=list)
    currency_default: str = "USD"
    locale: dict[str, Any] = field(default_factory=dict)


def parse_mapping_config(raw: dict[str, Any], mapping_path: str = "<mapping>") -> MappingConfig:
    """Parse and validate a raw mapping dict into a typed MappingConfig."""
    required_keys = ["bank_key", "bank_name", "amount_format_family", "column_map", "date"]
    for key in required_keys:
        if key not in raw:
            raise ValueError(f"Mapping {mapping_path} missing required key: {key!r}")

    family = raw["amount_format_family"]
    valid_families = {"signed", "debit_credit", "money_in_out", "amount_plus_flag"}
    if family not in valid_families:
        raise ValueError(
            f"Unknown amount_format_family {family!r}. Must be one of: {valid_families}"
        )

    date_raw = raw.get("date") or {}
    amount_raw = raw.get("amount") or {}

    if not date_raw.get("transaction_date"):
        raise ValueError(f"Mapping {mapping_path} must define date.transaction_date")

    if family == "signed" and not amount_raw.get("signed_amount"):
        # BUG FIX 3: allow signed family without signed_amount when the Feature 2
        # fallback pair (amount_debit / amount_credit) is present — resolve_amount()
        # step 2 handles those fields automatically.
        if not amount_raw.get("amount_debit") and not amount_raw.get("amount_credit"):
            raise ValueError(f"Mapping {mapping_path} must define amount.signed_amount for signed family")
    if family == "debit_credit" and (
        not amount_raw.get("debit_col") or not amount_raw.get("credit_col")
    ):
        raise ValueError(f"Mapping {mapping_path} must define amount.debit_col and amount.credit_col")
    if family == "money_in_out" and (
        not amount_raw.get("money_in_col") or not amount_raw.get("money_out_col")
    ):
        raise ValueError(f"Mapping {mapping_path} must define amount.money_in_col and amount.money_out_col")
    if family == "amount_plus_flag":
        if not amount_raw.get("amount_col") or not amount_raw.get("dc_flag_col"):
            raise ValueError(f"Mapping {mapping_path} must define amount.amount_col and amount.dc_flag_col")
        flags = amount_raw.get("dc_flag_values", {})
        debit_values = set(flags.get("debit", []))
        credit_values = set(flags.get("credit", []))
        if not debit_values or not credit_values:
            raise ValueError(
                f"Mapping {mapping_path} must define non-empty amount.dc_flag_values.debit/credit"
            )
        overlap = debit_values & credit_values
        if overlap:
            raise ValueError(f"Mapping {mapping_path} has overlapping debit/credit flags: {sorted(overlap)}")

    return MappingConfig(
        bank_key=str(raw["bank_key"]),
        bank_name=str(raw["bank_name"]),
        amount_format_family=family,
        column_map=dict(raw.get("column_map") or {}),
        date=DateConfig(
            transaction_date=str(date_raw["transaction_date"]),
            posted_date=date_raw.get("posted_date"),
            date_format=date_raw.get("date_format"),
        ),
        amount=AmountConfig(
            signed_amount=amount_raw.get("signed_amount"),
            debit_col=amount_raw.get("debit_col"),
            credit_col=amount_raw.get("credit_col"),
            money_in_col=amount_raw.get("money_in_col"),
            money_out_col=amount_raw.get("money_out_col"),
            amount_col=amount_raw.get("amount_col"),
            dc_flag_col=amount_raw.get("dc_flag_col"),
            dc_flag_values=dict(amount_raw.get("dc_flag_values") or {}),
        ),
        account_name=str(raw.get("account_name") or ""),
        account_id=str(raw.get("account_id") or ""),
        drop_columns=list(raw.get("drop_columns") or []),
        currency_default=str(raw.get("currency_default") or "USD"),
        locale=dict(raw.get("locale") or {}),
    )
