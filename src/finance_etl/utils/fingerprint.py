"""
Transaction fingerprint — stable SHA-256 over canonical fields.

Input fields (from database_design.txt §3):
  bank_name | account_id | transaction_date | normalized_description | amount | currency

Rules:
- description is uppercased + whitespace-collapsed before hashing.
- amount is formatted as a fixed-point string (e.g. "-123.45").
- All values joined with "|" separator.
- SHA-256 hex digest.
"""
from __future__ import annotations

import datetime
import hashlib
from decimal import Decimal

from finance_etl.utils.text import normalize_for_fingerprint


def compute_fingerprint(
    bank_name: str,
    account_id: str,
    transaction_date: datetime.date,
    description: str,
    amount: Decimal,
    currency: str = "USD",
) -> str:
    """Return a stable SHA-256 fingerprint for a transaction."""
    parts = [
        bank_name.strip(),
        account_id.strip(),
        transaction_date.isoformat(),
        normalize_for_fingerprint(description),
        f"{amount:.2f}",
        currency.strip().upper(),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
