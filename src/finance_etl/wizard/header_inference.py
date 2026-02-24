"""
Automated Header Mapping — Schema Inference
===========================================

Reads the first 5 rows of a bank CSV and uses keyword matching to
automatically map each column to the required config.yaml canonical fields.

Public function
---------------
infer_csv_headers(file_path: str) -> dict

Returned dict keys
------------------
column_map          : {raw_header: canonical_field}   – drop omitted
date                : date config section (transaction_date, posted_date, date_format)
amount              : amount config section (varies by family)
amount_format_family: "signed" | "debit_credit" | "money_in_out"
drop_columns        : columns with no canonical match
raw_headers         : original header list (for UI display)
sample_values       : {raw_header: [up to 5 sample strings]}
confidence          : {canonical_field: score 0-1}
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Optional

import chardet


# ---------------------------------------------------------------------------
# Keyword lookup tables
# ---------------------------------------------------------------------------
# Keys are canonical field names; values are ordered lists of lowercase
# substrings. The *first match* wins, so put longer / more-specific phrases
# before shorter ones to avoid "date" stealing "posted date".

_FIELD_KEYWORDS: dict[str, list[str]] = {
    "transaction_date": [
        "trans date",
        "transaction date",
        "txn date",
        "tran date",
        "value date",
        "effective date",
        "settlement date",
        "trx date",
        "trade date",
        "date",
    ],
    "posted_date": [
        "post date",
        "posting date",
        "posted date",
        "cleared date",
        "post",
        "posted",
    ],
    "description": [
        "description",
        "desc",
        "memo",
        "payee",
        "narrative",
        "narration",
        "detail",
        "reference",
        "particulars",
        "note",
        "merchant",
        "transaction detail",
        "activity",
    ],
    "amount": [
        "net amount",
        "transaction amount",
        "payment amount",
        "amount",
        "value",
        "total",
    ],
    "debit": [
        "debit amount",
        "debit",
        "withdrawals",
        "withdrawal",
        "dr",
        "charges",
        "debits",
    ],
    "credit": [
        "credit amount",
        "credit",
        "deposits",
        "deposit",
        "cr",
        "credits",
        "payments",
    ],
    "money_out": [
        "money out",
        "money_out",
        "outflow",
        "outgoing",
        "paid out",
    ],
    "money_in": [
        "money in",
        "money_in",
        "inflow",
        "incoming",
        "paid in",
    ],
    "balance": [
        "running balance",
        "closing balance",
        "available balance",
        "balance",
    ],
    "category": [
        "transaction type",
        "txn type",
        "category",
        "type",
    ],
}

# Evaluation order: more specific fields before their shorter sub-patterns.
_ORDERED_FIELDS = [
    "transaction_date",
    "posted_date",
    "description",
    "debit",
    "credit",
    "money_out",
    "money_in",
    "amount",
    "balance",
    "category",
]


# ---------------------------------------------------------------------------
# Core matching helpers
# ---------------------------------------------------------------------------

def _normalise_header(header: str) -> str:
    """Lowercase, collapse whitespace, strip wrapping quotes."""
    h = header.strip().strip('"').strip("'").lower()
    return re.sub(r"\s+", " ", h)


def _ranked_matches(header: str) -> list[str]:
    """
    Return all canonical fields that match *header*, ordered by priority.

    Using a ranked list (rather than a single best match) allows the caller
    to skip already-used fields and fall through to the next candidate.
    For example "Post Date" ranks [posted_date, transaction_date] so it
    correctly maps to posted_date when transaction_date is already claimed.
    """
    h = _normalise_header(header)
    seen: set[str] = set()
    results: list[str] = []
    for field in _ORDERED_FIELDS:
        for kw in _FIELD_KEYWORDS[field]:
            if kw in h and field not in seen:
                results.append(field)
                seen.add(field)
                break
    return results


def _detect_amount_family(matched: dict[str, str]) -> tuple[str, dict]:
    """
    Infer the amount_format_family from whichever canonical amount columns
    were matched, and build the corresponding ``amount`` config section.

    Priority:
      1. debit + credit columns → debit_credit
      2. money_in + money_out   → money_in_out
      3. amount column only     → signed
    """
    if "debit" in matched and "credit" in matched:
        return "debit_credit", {
            "debit_col": matched["debit"],
            "credit_col": matched["credit"],
        }
    if "money_in" in matched and "money_out" in matched:
        return "money_in_out", {
            "money_in_col": matched["money_in"],
            "money_out_col": matched["money_out"],
        }
    if "amount" in matched:
        return "signed", {"signed_amount": matched["amount"]}
    # No amount column found — default to signed with empty config.
    return "signed", {}


# ---------------------------------------------------------------------------
# Date format guessing
# ---------------------------------------------------------------------------

_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"),        "%Y-%m-%d"),    # 2024-01-31
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"),         "%m/%d/%Y"),    # 01/31/2024
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"),         "%m-%d-%Y"),    # 01-31-2024
    (re.compile(r"^\d{2}/\d{2}/\d{2}$"),         "%m/%d/%y"),    # 01/31/24
    (re.compile(r"^\d{4}/\d{2}/\d{2}$"),         "%Y/%m/%d"),    # 2024/01/31
    (re.compile(r"^\d{2}\.\d{2}\.\d{4}$"),       "%d.%m.%Y"),    # 31.01.2024
    (re.compile(r"^\d{1,2}\s+\w+\s+\d{4}$"),    "%d %B %Y"),    # 31 January 2024
    (re.compile(r"^\w+\s+\d{1,2},\s+\d{4}$"),   "%B %d, %Y"),   # January 31, 2024
]


def _guess_date_format(values: list[str]) -> str:
    """Return the most likely strptime format string for *values*."""
    for value in values:
        v = value.strip()
        if not v:
            continue
        for pattern, fmt in _DATE_PATTERNS:
            if pattern.match(v):
                return fmt
    return "%Y-%m-%d"  # safe ISO default


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def infer_csv_headers(file_path: str) -> dict:
    """
    Read the first 5 data rows of *file_path* and automatically map its
    columns to the canonical config.yaml fields using keyword matching.

    Parameters
    ----------
    file_path : str
        Path to the bank CSV export.

    Returns
    -------
    dict with the following keys:

    column_map : dict[str, str]
        Maps raw CSV header → canonical field name.
        Only matched columns are included; unmatched ones appear in
        ``drop_columns``.

    date : dict
        Date config section.  Keys: ``transaction_date``, optionally
        ``posted_date``, and ``date_format``.

    amount : dict
        Amount config section.  Structure depends on ``amount_format_family``.

    amount_format_family : str
        One of ``"signed"``, ``"debit_credit"``, or ``"money_in_out"``.

    drop_columns : list[str]
        Raw headers that could not be matched to any canonical field.

    raw_headers : list[str]
        Original header row (preserved for review in the UI/wizard).

    sample_values : dict[str, list[str]]
        Up to 5 sample cell values per column header.

    confidence : dict[str, float]
        Confidence score (0–1) per matched canonical field.
        Currently binary (1.0 = matched, absent = not matched).

    Also prints a concise human-readable summary to stdout.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    # ------------------------------------------------------------------
    # 1. Detect encoding
    # ------------------------------------------------------------------
    with open(path, "rb") as fh:
        raw_bytes = fh.read(32_768)
    enc_result = chardet.detect(raw_bytes)
    encoding: str = enc_result.get("encoding") or "utf-8"

    # ------------------------------------------------------------------
    # 2. Read first 5 rows
    # ------------------------------------------------------------------
    with open(path, encoding=encoding, errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))

    if not rows:
        raise ValueError(f"CSV file is empty: {file_path}")

    # Skip any leading blank rows.
    start = 0
    while start < len(rows) and not any(c.strip() for c in rows[start]):
        start += 1

    if start >= len(rows):
        raise ValueError(f"No data found in CSV: {file_path}")

    raw_headers: list[str] = [h.strip() for h in rows[start]]
    data_rows = rows[start + 1: start + 6]  # up to 5 data rows

    # ------------------------------------------------------------------
    # 3. Keyword matching — map each header to a canonical field
    # ------------------------------------------------------------------
    # matched  : canonical_field → raw_header  (first match wins per field)
    # column_map: raw_header      → canonical_field
    matched: dict[str, str] = {}
    column_map: dict[str, str] = {}
    drop_columns: list[str] = []
    used_fields: set[str] = set()
    confidence: dict[str, float] = {}

    for header in raw_headers:
        # Try candidates in priority order; pick the first unused field.
        assigned: Optional[str] = None
        for field in _ranked_matches(header):
            if field not in used_fields:
                assigned = field
                break
        if assigned:
            matched[assigned] = header
            column_map[header] = assigned
            used_fields.add(assigned)
            confidence[assigned] = 1.0
        else:
            drop_columns.append(header)

    # ------------------------------------------------------------------
    # 4. Collect sample values per column
    # ------------------------------------------------------------------
    sample_values: dict[str, list[str]] = {
        header: [row[i] if i < len(row) else "" for row in data_rows]
        for i, header in enumerate(raw_headers)
    }

    # ------------------------------------------------------------------
    # 5. Guess date format from sample values of the transaction_date col
    # ------------------------------------------------------------------
    date_col = matched.get("transaction_date")
    date_fmt = _guess_date_format(
        sample_values.get(date_col, []) if date_col else []
    )

    date_section: dict = {}
    if date_col:
        date_section["transaction_date"] = date_col
        date_section["date_format"] = date_fmt
    if "posted_date" in matched:
        date_section["posted_date"] = matched["posted_date"]

    # ------------------------------------------------------------------
    # 6. Detect amount family and build amount section
    # ------------------------------------------------------------------
    family, amount_section = _detect_amount_family(matched)

    # ------------------------------------------------------------------
    # 7. Assemble and return
    # ------------------------------------------------------------------
    result = {
        "column_map": column_map,
        "date": date_section,
        "amount": amount_section,
        "amount_format_family": family,
        "drop_columns": drop_columns,
        "raw_headers": raw_headers,
        "sample_values": sample_values,
        "confidence": confidence,
    }

    _print_summary(result)
    return result


# ---------------------------------------------------------------------------
# Pretty-print summary
# ---------------------------------------------------------------------------

def _print_summary(result: dict) -> None:
    raw_headers: list[str] = result["raw_headers"]
    print("\n=== Header Inference Summary ===")
    print(f"Columns found ({len(raw_headers)}): {', '.join(raw_headers)}")
    print("\nColumn mapping:")
    for raw, canonical in result["column_map"].items():
        print(f"  {raw!r:35s} → {canonical}")
    if result["drop_columns"]:
        print(f"\nUnmatched (will be dropped): {', '.join(result['drop_columns'])}")
    print(f"\nAmount family : {result['amount_format_family']}")
    if result["date"]:
        print(f"Date format   : {result['date'].get('date_format', 'unknown')}")
    print("=" * 33)
