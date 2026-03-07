"""
Wizard mapping — header inference, profile persistence, YAML merge.

Provides the business logic for the CSV header-mapping wizard:
  - Extract headers + sample rows from an uploaded CSV
  - Fuzzy-match detected headers against existing wizard profiles to auto-suggest
  - Validate that required canonical fields are covered
  - Merge new header aliases into existing profiles (additive, never destructive)
  - Convert a wizard mapping selection to a pipeline-compatible config dict

YAML profile format (config/wizard_profiles/<institution>/<account_id>.yaml):

  institution: chase
  account_id:  checking_1234
  account_name: My Checking
  bank_name: Chase Bank
  created_at: "2026-02-24T07:00:00+00:00"
  profiles:
    default:
      amount_mode: debit_credit   # signed | debit_credit | money_in_out | amount_plus_flag
      canonical_map:
        transaction_date:
          aliases: ["Transaction Date", "Posting Date", "Date"]
        bank_debit:
          aliases: ["Debit Amount", "Withdrawals"]
        bank_credit:
          aliases: ["Credit Amount", "Deposits"]
        description:
          aliases: ["Description", "Details"]
      date_format: "%m/%d/%Y"
      currency_default: USD
      drop_columns: []
      created_at: "2026-02-24T07:00:00+00:00"
      updated_at: "2026-02-24T07:00:00+00:00"

Alias arrays are always APPENDED (case-insensitive dedup); never deleted.

Canonical field names are scoped by statement_type:
  Credit card: cc_amount | cc_charge + cc_payment
  Bank:        bank_amount | bank_debit + bank_credit | debit_amount + credit_amount |
               money_in + money_out | bank_amount + dc_flag
"""
from __future__ import annotations

import csv
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Canonical fields the wizard can map to
# ---------------------------------------------------------------------------
# Fields are scoped by statement_type:
#   credit_card: cc_amount / cc_charge / cc_payment
#   bank:        bank_amount / bank_debit / bank_credit /
#                debit_amount / credit_amount / money_in / money_out / dc_flag
#
# Old names (amount, amount_debit, amount_credit) have been retired.
# wizard_mapping.py raises a clear error if they are submitted.
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: list[str] = [
    # Required
    "transaction_date",
    # ── Credit-card amount fields (scoped to statement_type=credit_card) ──
    "cc_amount",    # Single signed/unsigned amount column — polarity confirmed by user
    "cc_charge",    # Money charged to the card (Format C debit col → spending)
    "cc_payment",   # Money paid toward the card balance (Format C credit col → payment)
    # ── Bank amount fields (scoped to statement_type=bank) ────────────────
    "bank_amount",  # Single signed/unsigned amount on a bank statement
    "bank_debit",   # Money leaving the bank account (debit_credit family)
    "bank_credit",  # Money entering the bank account (debit_credit family)
    # Bank family: debit_credit (legacy column names kept for back-compat profiles)
    "debit_amount", # Pair with credit_amount → debit_credit family
    "credit_amount",
    # Bank family: money_in_out
    "money_in",     # Pair with money_out → money_in_out family
    "money_out",
    # Bank family: amount_plus_flag
    "dc_flag",      # Combined with bank_amount → amount_plus_flag family
    # ── Shared optional metadata ───────────────────────────────────────────
    "description",
    "posted_date",
    "merchant",
    "category",
    "account",
    "notes",
    "currency",
]

# Fields that are ONLY valid for credit-card statements
CC_ONLY_FIELDS: set[str] = {"cc_amount", "cc_charge", "cc_payment"}

# Fields that are ONLY valid for bank statements
BANK_ONLY_FIELDS: set[str] = {
    "bank_amount", "bank_debit", "bank_credit",
    "debit_amount", "credit_amount",
    "money_in", "money_out",
    "dc_flag",
}

# Old field names that have been renamed — submitted values raise a clear error
_RETIRED_FIELD_NAMES: set[str] = {"amount", "amount_debit", "amount_credit"}

# Fields shown in wizard step 2 scoped by statement_type
CC_CANONICAL_FIELDS: list[str] = [
    "transaction_date",
    "cc_amount", "cc_charge", "cc_payment",
    "description", "posted_date", "merchant", "category", "account", "notes", "currency",
]

BANK_CANONICAL_FIELDS: list[str] = [
    "transaction_date",
    "bank_amount", "bank_debit", "bank_credit",
    "debit_amount", "credit_amount",
    "money_in", "money_out",
    "dc_flag",
    "description", "posted_date", "merchant", "category", "account", "notes", "currency",
]

REQUIRED_FIELDS: set[str] = {"transaction_date"}

# CC amount groups — any fully-present group = valid CC mapping
CC_AMOUNT_GROUPS: list[set[str]] = [
    {"cc_charge", "cc_payment"},   # Format C — two-column
    {"cc_amount"},                 # Format A / B — single column, polarity confirmed
]

# Bank amount groups — any fully-present group = valid bank mapping
BANK_AMOUNT_GROUPS: list[set[str]] = [
    {"bank_debit", "bank_credit"},
    {"bank_amount"},
    {"debit_amount", "credit_amount"},
    {"money_in", "money_out"},
]

# Union — used for validation when statement_type is unknown
AMOUNT_GROUPS: list[set[str]] = CC_AMOUNT_GROUPS + BANK_AMOUNT_GROUPS

# Labels shown in the wizard UI
CANONICAL_LABELS: dict[str, str] = {
    "transaction_date": "Transaction Date *",
    "posted_date":      "Posted / Settlement Date",
    # Credit-card labels
    "cc_amount":        "Amount (single column — polarity confirmed below) *",
    "cc_charge":        "Charge / Debit (money charged to card) *",
    "cc_payment":       "Payment / Credit (money paid toward card) *",
    # Bank labels
    "bank_amount":      "Amount (signed: positive = inflow) *",
    "bank_debit":       "Debit / Withdrawal Amount *",
    "bank_credit":      "Credit / Deposit Amount *",
    "debit_amount":     "Debit / Withdrawal Amount (legacy)",
    "credit_amount":    "Credit / Deposit Amount (legacy)",
    "money_in":         "Money In *",
    "money_out":        "Money Out *",
    "dc_flag":          "Debit/Credit Flag *",
    # Shared optional
    "description":      "Description / Narrative",
    "merchant":         "Merchant / Payee",
    "category":         "Category",
    "account":          "Account",
    "notes":            "Notes / Memo",
    "currency":         "Currency",
}

# Keyword hints per canonical field (all lowercase, no punctuation)
_FIELD_KEYWORDS: dict[str, list[str]] = {
    "transaction_date": [
        "transactiondate", "txndate", "transdate", "txdate",
        "valuedate", "date",
    ],
    "posted_date": [
        "postdate", "posteddate", "settlementdate", "cleardate",
        "postingdate",
    ],
    # Credit-card keywords
    "cc_amount": [
        "amount", "amt", "transactionamount", "txnamount",
    ],
    "cc_charge": [
        "charge", "charges", "debit", "debitamount", "withdrawal", "withdrawals",
    ],
    "cc_payment": [
        "payment", "payments", "credit", "creditamount", "deposit",
    ],
    # Bank keywords
    "bank_amount": [
        "amount", "amt", "transactionamount", "net",
    ],
    "bank_debit": [
        "debit", "debitamount", "debitamt", "withdrawal", "withdrawals", "dr",
    ],
    "bank_credit": [
        "credit", "creditamount", "creditamt", "deposit", "deposits", "cr",
    ],
    "debit_amount": [
        "debit", "debitamount", "debitamt", "withdrawal", "withdrawals",
    ],
    "credit_amount": [
        "credit", "creditamount", "creditamt", "deposit", "deposits",
    ],
    "money_in": [
        "moneyin", "moneyreceived", "income", "received",
    ],
    "money_out": [
        "moneyout", "moneyspent", "spent",
    ],
    "dc_flag": [
        "dc", "drcrflag", "drcr", "drcrind", "creditdebit", "flag",
    ],
    "description": [
        "description", "desc", "memo", "narrative", "narration",
        "detail", "particulars", "payee", "reference",
    ],
    "merchant": ["merchant", "vendor", "shop"],
    "category": ["category", "cat", "classification"],
    "account":  ["account", "accountname", "accountno", "accountnumber"],
    "notes":    ["notes", "note", "comment", "remarks"],
    "currency": ["currency", "ccy", "currencycode"],
}

# ---------------------------------------------------------------------------
# CC format detection synonyms (used client-side and server-side for detection)
# ---------------------------------------------------------------------------

# Headers whose normalized key contains one of these → likely cc_charge column
CC_CHARGE_SYNONYMS: set[str] = {
    "charge", "charges", "debit", "debitamount", "withdrawal", "withdrawals",
}

# Headers whose normalized key contains one of these → likely cc_payment column
CC_PAYMENT_SYNONYMS: set[str] = {
    "payment", "payments", "credit", "creditamount", "deposit", "deposits",
}


def _normalize_key(s: str) -> str:
    """Lowercase + strip all non-alphanumeric characters for fuzzy comparison."""
    s = unicodedata.normalize("NFC", s).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _suggest_canonical_for_header(header: str) -> str | None:
    """Return the best-guess canonical field name for a single CSV header."""
    key = _normalize_key(header)
    best: tuple[int, str] | None = None
    for field, keywords in _FIELD_KEYWORDS.items():
        for kw in keywords:
            if kw in key or key in kw:
                # Longer keyword = more specific = preferred
                score = len(kw)
                if best is None or score > best[0]:
                    best = (score, field)
    return best[1] if best else None


def suggest_mappings(
    headers: list[str],
    statement_type: str | None = None,
) -> dict[str, str | None]:
    """
    Return {canonical_field: best_csv_header} suggestions via keyword matching.

    Each canonical field gets at most one suggestion; each CSV header is used
    for at most one canonical field (first-match wins).

    When statement_type is provided, only canonical fields valid for that type
    are included in the result.
    """
    used_headers: set[str] = set()

    # Scope fields by statement_type
    if statement_type == "credit_card":
        scope = CC_CANONICAL_FIELDS
    elif statement_type == "bank":
        scope = BANK_CANONICAL_FIELDS
    else:
        scope = CANONICAL_FIELDS

    result: dict[str, str | None] = {f: None for f in scope}

    for header in headers:
        canonical = _suggest_canonical_for_header(header)
        if canonical and canonical in result and result[canonical] is None and header not in used_headers:
            result[canonical] = header
            used_headers.add(header)

    return result


def get_canonical_fields_for_type(statement_type: str | None) -> list[str]:
    """Return the ordered list of canonical fields to show in the wizard for a given statement_type."""
    if statement_type == "credit_card":
        return CC_CANONICAL_FIELDS
    if statement_type == "bank":
        return BANK_CANONICAL_FIELDS
    return CANONICAL_FIELDS


def detect_cc_format(headers: list[str]) -> str | None:
    """
    Detect the credit-card amount format from CSV headers.

    Returns:
      'two_col'    — headers contain both a cc_charge and a cc_payment synonym
      'single_col' — only one amount-like column (Format A / B)
      None         — inconclusive (no amount columns detected)
    """
    normed = {_normalize_key(h) for h in headers}

    has_charge  = any(any(s in n for s in CC_CHARGE_SYNONYMS)  for n in normed)
    has_payment = any(any(s in n for s in CC_PAYMENT_SYNONYMS) for n in normed)

    if has_charge and has_payment:
        return "two_col"
    # If only one of charge/payment present, or a generic amount column
    amount_synonyms = {"amount", "amt", "transactionamount", "net"}
    has_amount = any(any(s in n for s in amount_synonyms) for n in normed)
    if has_amount or has_charge or has_payment:
        return "single_col"
    return None


# Synonyms for detecting separate debit/credit columns in bank CSVs
_BANK_DEBIT_SYNONYMS: set[str] = {
    "debit", "debitamount", "debitamt", "withdrawal", "withdrawals", "dr", "moneyin",
}
_BANK_CREDIT_SYNONYMS: set[str] = {
    "credit", "creditamount", "creditamt", "deposit", "deposits", "cr", "moneyout",
}


def detect_bank_format(headers: list[str]) -> str | None:
    """
    Detect the bank statement amount format from CSV headers.

    Returns:
      'two_col'    — headers contain both a debit and a credit column
      'single_col' — only one amount-like column
      None         — inconclusive (no amount columns detected)
    """
    normed = {_normalize_key(h) for h in headers}

    has_debit  = any(any(s in n for s in _BANK_DEBIT_SYNONYMS)  for n in normed)
    has_credit = any(any(s in n for s in _BANK_CREDIT_SYNONYMS) for n in normed)

    if has_debit and has_credit:
        return "two_col"
    amount_synonyms = {"amount", "amt", "transactionamount", "net", "balance"}
    has_amount = any(any(s in n for s in amount_synonyms) for n in normed)
    if has_amount or has_debit or has_credit:
        return "single_col"
    return None


# ---------------------------------------------------------------------------
# Date format detection
# ---------------------------------------------------------------------------

# Comprehensive ordered list of strptime formats.
# Ordering rules:
#   1. Fully unambiguous formats first (ISO / year-first / named-month).
#   2. 4-digit-year regional formats before 2-digit-year variants.
#   3. Datetime (with time component) variants after their date-only equivalents.
#   4. Compact no-separator and Julian formats last (most ambiguous).
#
# In Python strptime, %m and %d match both padded (01) and unpadded (1) numbers,
# so "D/M/YYYY" and "DD/MM/YYYY" collapse to a single format string.
_CANDIDATE_DATE_FORMATS: list[str] = [
    # ── Fully unambiguous: ISO 8601 / year-first ──────────────────────────
    "%Y-%m-%d",             # 2025-01-15
    "%Y/%m/%d",             # 2025/01/15
    "%Y.%m.%d",             # 2025.01.15
    "%Y%m%d",               # 20250115

    # ── ISO 8601 with time component ──────────────────────────────────────
    "%Y-%m-%dT%H:%M:%S",    # 2025-01-15T10:30:00
    "%Y-%m-%dT%H:%M",       # 2025-01-15T10:30
    "%Y-%m-%d %H:%M:%S",    # 2025-01-15 10:30:00
    "%Y-%m-%d %H:%M",       # 2025-01-15 10:30
    "%Y%m%dT%H%M%S",        # 20250115T103000

    # ── Named month — day/year position is unambiguous ────────────────────
    "%d %b %Y",             # 15 Jan 2025
    "%d-%b-%Y",             # 15-Jan-2025
    "%d %B %Y",             # 15 January 2025
    "%b %d, %Y",            # Jan 15, 2025
    "%b %d %Y",             # Jan 15 2025
    "%B %d, %Y",            # January 15, 2025
    "%B %d %Y",             # January 15 2025
    "%d %b %y",             # 15 Jan 25
    "%d-%b-%y",             # 15-Jan-25
    "%d %B %y",             # 15 January 25
    "%b %d, %y",            # Jan 15, 25
    "%b %d %y",             # Jan 15 25
    "%B %d, %y",            # January 15, 25
    "%B %d %y",             # January 15 25
    # Long written styles
    "%A, %B %d, %Y",        # Monday, January 15, 2025
    "%a, %b-%d-%Y",         # Mon, Jan-15-2025

    # ── 4-digit year with separators (US ordering first) ──────────────────
    "%m/%d/%Y",             # 01/15/2025 — US slash
    "%d/%m/%Y",             # 15/01/2025 — EU slash
    "%m-%d-%Y",             # 01-15-2025 — US dash
    "%d-%m-%Y",             # 15-01-2025 — EU dash
    "%d.%m.%Y",             # 15.01.2025 — EU/DE dot
    "%m.%d.%Y",             # 01.15.2025 — US dot

    # ── 4-digit year datetime with separators ─────────────────────────────
    "%m/%d/%Y %H:%M:%S",    # 01/15/2025 10:30:00
    "%m/%d/%Y %H:%M",       # 01/15/2025 10:30
    "%d/%m/%Y %H:%M:%S",    # 15/01/2025 10:30:00
    "%d/%m/%Y %H:%M",       # 15/01/2025 10:30

    # ── 2-digit year with separators ──────────────────────────────────────
    "%m/%d/%y",             # 01/15/25 — US slash
    "%d/%m/%y",             # 15/01/25 — EU slash
    "%y/%m/%d",             # 25/01/15 — Asian/ISO-short
    "%m-%d-%y",             # 01-15-25
    "%d-%m-%y",             # 15-01-25
    "%y-%m-%d",             # 25-01-15
    "%d.%m.%y",             # 15.01.25
    "%y.%m.%d",             # 25.01.15

    # ── 2-digit year datetime ─────────────────────────────────────────────
    "%m/%d/%y %H:%M:%S",    # 01/15/25 10:30:00
    "%d/%m/%y %H:%M:%S",    # 15/01/25 10:30:00

    # ── Month + Year only (day defaults to 1 when parsed) ─────────────────
    "%b %Y",                # Jan 2025
    "%B %Y",                # January 2025
    "%b %y",                # Jan 25
    "%B %y",                # January 25
    "%m/%Y",                # 01/2025
    "%Y-%m",                # 2025-01
    "%Y/%m",                # 2025/01
    "%m-%Y",                # 01-2025
    "%m.%Y",                # 01.2025

    # ── Compact 8-digit no-separator (DDMMYYYY / MMDDYYYY) ───────────────
    "%d%m%Y",               # 15012025 — EU compact
    "%m%d%Y",               # 01152025 — US compact

    # ── Compact 6-digit no-separator (most ambiguous — try last) ─────────
    "%y%m%d",               # 250115  — YY MM DD
    "%d%m%y",               # 150125  — DD MM YY
    "%m%d%y",               # 011525  — MM DD YY

    # ── Julian / ordinal day-of-year ──────────────────────────────────────
    "%Y%j",                 # 2025015  — YYYYDDD
    "%y%j",                 # 25015    — YYDDD
    "%Y/%j",                # 2025/015 — YYYY/DDD
    "%y/%j",                # 25/015   — YY/DDD
    "%j/%Y",                # 015/2025 — DDD/YYYY
    "%j/%y",                # 015/25   — DDD/YY
]


def detect_date_format(values: list[str]) -> str | None:
    """
    Infer a strptime date_format from a list of sample date strings.

    Tries each candidate format in order and returns the first one that
    successfully parses *all* non-empty sample values.  Returns None when
    the list is empty or no single format matches every value.

    Example
    -------
    >>> detect_date_format(["01/05/2024", "01/15/2024"])
    '%m/%d/%Y'
    """
    clean = [v.strip() for v in values if v and v.strip()]
    if not clean:
        return None

    for fmt in _CANDIDATE_DATE_FORMATS:
        if all(_try_strptime(v, fmt) for v in clean):
            return fmt

    return None


def _try_strptime(value: str, fmt: str) -> bool:
    import datetime as _dt
    v = value.strip()
    # Strip fractional seconds (e.g. "2025-01-15T10:30:00.123456") so that
    # datetime formats without %f still match timestamp columns.
    if ":" in v and "." in v:
        v = re.sub(r"\.\d+$", "", v)
    try:
        _dt.datetime.strptime(v, fmt)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Column-agnostic date format scanner
# ---------------------------------------------------------------------------

def _detect_date_format_any_col(
    headers: list[str],
    sample_rows: list[dict[str, str]],
    suggestions: dict[str, str | None],
) -> str | None:
    """
    Detect the date format from sample rows without depending on the column mapping.

    Tries columns in priority order:
      1. Suggested transaction_date / posted_date columns (highest confidence)
      2. Columns whose name contains date-like keywords
      3. All remaining columns

    Returns the first format string that parses all non-empty values in any column,
    or None if no column yields a consistent date format.
    """
    if not sample_rows:
        return None

    # Build priority-ordered list of column names to probe
    tried: set[str] = set()
    ordered: list[str] = []

    # Priority 1 — explicitly suggested date fields
    for field in ("transaction_date", "posted_date"):
        col = suggestions.get(field)
        if col and col not in tried:
            ordered.append(col)
            tried.add(col)

    # Priority 2 — headers whose name looks date-like
    _date_kws = re.compile(r"date|dt|posted|trans|time|val", re.IGNORECASE)
    for h in headers:
        if h not in tried and _date_kws.search(re.sub(r"[^\w]", "", h)):
            ordered.append(h)
            tried.add(h)

    # Priority 3 — everything else
    for h in headers:
        if h not in tried:
            ordered.append(h)
            tried.add(h)

    for col in ordered:
        values = [row.get(col, "").strip() for row in sample_rows]
        non_empty = [v for v in values if v]
        if not non_empty:
            continue
        fmt = detect_date_format(non_empty)
        if fmt:
            return fmt

    return None


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def extract_csv_headers(
    file_path: str | Path,
    max_sample_rows: int = 5,
    statement_type: str | None = None,
) -> dict[str, Any]:
    """
    Detect encoding, delimiter, and headers from a CSV file.

    Returns:
      {
        "headers":               list[str],
        "sample_rows":           list[dict[str, str]],
        "encoding":              str,
        "delimiter":             str,
        "row_count_estimate":    int,
        "suggestions":           dict[str, str | None],
        "suggested_date_format": str | None,   # inferred from date column samples
      }
    """
    from finance_etl.utils.csv_sniff import sniff_csv

    profile = sniff_csv(file_path)
    headers = profile["headers"]
    encoding = profile["encoding"]
    delimiter = profile["delimiter"]
    row_count = profile["row_count_estimate"]

    sample_rows: list[dict[str, str]] = []
    try:
        with open(file_path, encoding=encoding, errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for i, row in enumerate(reader):
                if i >= max_sample_rows:
                    break
                sample_rows.append(
                    {k.strip(): (v or "").strip() for k, v in row.items() if k}
                )
    except Exception:
        pass

    suggestions = suggest_mappings(headers, statement_type=statement_type)

    # Detect amount format from headers (statement-type-aware)
    cc_format   = detect_cc_format(headers)   if statement_type == "credit_card" else None
    bank_format = detect_bank_format(headers) if statement_type == "bank" else None

    # ── Date format detection — always runs, independent of mapping ────────
    # Strategy: try suggested date columns first (high confidence), then scan
    # every remaining column so that unusual header names never block detection.
    suggested_date_format = _detect_date_format_any_col(headers, sample_rows, suggestions)

    return {
        "headers":               headers,
        "sample_rows":           sample_rows,
        "encoding":              encoding,
        "delimiter":             delimiter,
        "row_count_estimate":    row_count,
        "suggestions":           suggestions,
        "suggested_date_format": suggested_date_format,
        "cc_format":             cc_format,    # 'two_col' | 'single_col' | None
        "bank_format":           bank_format,  # 'two_col' | 'single_col' | None
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_wizard_mapping(
    canonical_map: dict[str, str | None],
    statement_type: str | None = None,
) -> list[str]:
    """
    Check that the wizard mapping satisfies minimum requirements.

    Returns a list of human-readable error strings (empty list = OK).
    """
    errors: list[str] = []

    # Reject retired field names with a clear migration message
    retired_used = _RETIRED_FIELD_NAMES & set(canonical_map.keys())
    if retired_used:
        retired_sorted = sorted(retired_used)
        errors.append(
            f"Retired canonical field name(s) submitted: {retired_sorted}. "
            "Use cc_amount / cc_charge / cc_payment for credit cards, "
            "or bank_amount / bank_debit / bank_credit for bank statements."
        )
        return errors  # can't proceed with further validation

    if not canonical_map.get("transaction_date"):
        errors.append(
            "transaction_date is required — select the column containing the transaction date."
        )

    mapped = {k for k, v in canonical_map.items() if v}

    # Select the right amount groups based on statement_type
    if statement_type == "credit_card":
        valid_groups = CC_AMOUNT_GROUPS
        hint = "map the Amount column, or map both Charge and Payment columns."
    elif statement_type == "bank":
        valid_groups = BANK_AMOUNT_GROUPS
        hint = "map the Amount column, or map both Debit and Credit columns."
    else:
        valid_groups = AMOUNT_GROUPS
        hint = "map the Amount column, or map both Debit and Credit columns."

    if not any(group <= mapped for group in valid_groups):
        errors.append(f"Amount mapping required — {hint}")

    return errors


def infer_amount_mode(canonical_map: dict[str, str | None]) -> str:
    """Infer the pipeline amount_format_family from selected canonical fields."""
    mapped = {k for k, v in canonical_map.items() if v}
    # Two-column cc (Format C) → debit_credit family
    if "cc_charge" in mapped and "cc_payment" in mapped:
        return "debit_credit"
    # Single-col cc → signed family
    if "cc_amount" in mapped:
        return "signed"
    # Bank two-column new names
    if "bank_debit" in mapped and "bank_credit" in mapped:
        return "debit_credit"
    # Bank single-col new name
    if "bank_amount" in mapped:
        if "dc_flag" in mapped:
            return "amount_plus_flag"
        return "signed"
    # Bank legacy family names
    if "debit_amount" in mapped and "credit_amount" in mapped:
        return "debit_credit"
    if "money_in" in mapped and "money_out" in mapped:
        return "money_in_out"
    return "signed"


# ---------------------------------------------------------------------------
# Wizard profile YAML — persistence + additive merge
# ---------------------------------------------------------------------------

def _profile_path(profiles_dir: Path, institution: str, account_id: str) -> Path:
    safe_inst = re.sub(r"[^a-z0-9_-]", "_", institution.lower().strip()) or "unknown"
    safe_acc  = re.sub(r"[^a-z0-9_-]", "_", account_id.lower().strip())  or "default"
    return profiles_dir / safe_inst / f"{safe_acc}.yaml"


def load_wizard_profile(
    profiles_dir: Path,
    institution: str,
    account_id: str,
) -> dict | None:
    """Load an existing wizard profile YAML, or return None if not found."""
    path = _profile_path(profiles_dir, institution, account_id)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_wizard_profile(profiles_dir: Path, profile: dict) -> Path:
    """Write a wizard profile dict to its YAML file (creates parent dirs)."""
    institution = profile.get("institution", "unknown")
    account_id  = profile.get("account_id",  "default")
    path = _profile_path(profiles_dir, institution, account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(profile, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return path


def merge_wizard_profile(
    existing: dict | None,
    institution: str,
    account_id: str,
    account_name: str,
    bank_name: str,
    profile_name: str,
    canonical_map: dict[str, str | None],
    amount_mode: str,
    date_format: str | None,
    currency_default: str = "USD",
    drop_columns: list[str] | None = None,
    custom_headers: list[str] | None = None,
) -> dict:
    """
    Merge a new wizard selection into an existing profile (additive).

    Rules:
    - aliases arrays are APPENDED (case-insensitive dedup); never deleted
    - amount_mode, date_format, currency_default are updated if provided
    - updated_at is always refreshed

    Returns the merged profile dict (caller must call save_wizard_profile to persist).
    """
    now = datetime.now(timezone.utc).isoformat()

    if existing is None:
        existing = {
            "institution":  institution,
            "account_id":   account_id,
            "account_name": account_name,
            "bank_name":    bank_name,
            "created_at":   now,
            "profiles":     {},
        }

    # Update top-level metadata
    existing["institution"]  = institution
    existing["account_id"]   = account_id
    existing["account_name"] = account_name or existing.get("account_name", "")
    existing["bank_name"]    = bank_name    or existing.get("bank_name", "")

    profiles = existing.setdefault("profiles", {})
    prof = profiles.setdefault(profile_name, {
        "amount_mode":      amount_mode,
        "canonical_map":    {},
        "date_format":      date_format,
        "currency_default": currency_default,
        "drop_columns":     list(drop_columns or []),
        "created_at":       now,
    })

    # Update scalars
    prof["amount_mode"]      = amount_mode
    prof["currency_default"] = currency_default
    prof["updated_at"]       = now
    if date_format:
        prof["date_format"] = date_format

    # Merge aliases — additive, case-insensitive dedup, never delete
    canon_map_stored = prof.setdefault("canonical_map", {})
    for canonical_field, csv_header in canonical_map.items():
        if not csv_header:
            continue  # user left this field unmapped — skip, preserve existing aliases
        entry = canon_map_stored.setdefault(canonical_field, {"aliases": []})
        aliases: list[str] = entry.get("aliases") or []
        existing_lower = {a.lower() for a in aliases}
        if csv_header.lower() not in existing_lower:
            aliases.append(csv_header)
        entry["aliases"] = aliases

    # Persist non-canonical CSV column names — additive, case-insensitive dedup
    if custom_headers:
        saved: list[str] = prof.setdefault("custom_headers", [])
        saved_lower = {h.lower() for h in saved}
        for h in custom_headers:
            if h and h.lower() not in saved_lower:
                saved.append(h)
                saved_lower.add(h.lower())

    return existing


# ---------------------------------------------------------------------------
# Profile lookup — find best match for a set of CSV headers
# ---------------------------------------------------------------------------

def find_matching_profile(
    headers: list[str],
    profiles_dir: Path,
    match_threshold: float = 0.6,
) -> dict | None:
    """
    Search all wizard profiles for the best header match.

    Score = headers_found_in_aliases / total_canonical_fields_with_aliases.
    Returns None if no profile scores >= match_threshold.

    Return dict shape:
      {
        "score":        float,
        "institution":  str,
        "account_id":   str,
        "account_name": str,
        "bank_name":    str,
        "profile_name": str,
        "profile":      dict,   # the raw profile sub-dict
        "yaml_path":    str,
        "suggested_mapping": dict[str, str | None],
      }
    """
    if not profiles_dir.exists():
        return None

    headers_lower = {h.lower() for h in headers}
    best_score = 0.0
    best: dict | None = None

    for yaml_path in sorted(profiles_dir.rglob("*.yaml")):
        try:
            with open(yaml_path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        except Exception:
            continue

        for prof_name, prof in (doc.get("profiles") or {}).items():
            canon_map: dict = prof.get("canonical_map") or {}
            if not canon_map:
                continue

            hits = total = 0
            for entry in canon_map.values():
                aliases = [a.lower() for a in (entry.get("aliases") or [])]
                if aliases:
                    total += 1
                    if any(a in headers_lower for a in aliases):
                        hits += 1

            score = hits / total if total else 0.0
            if score > best_score:
                best_score = score
                best = {
                    "score":        round(score, 3),
                    "institution":  doc.get("institution", ""),
                    "account_id":   doc.get("account_id",  ""),
                    "account_name": doc.get("account_name", ""),
                    "bank_name":    doc.get("bank_name", ""),
                    "profile_name": prof_name,
                    "profile":      prof,
                    "yaml_path":    str(yaml_path),
                }

    if best and best_score >= match_threshold:
        # Build pre-filled mapping suggestions from first alias of each field
        suggested: dict[str, str | None] = {f: None for f in CANONICAL_FIELDS}
        canon_map = best["profile"].get("canonical_map") or {}
        headers_lower_map = {h.lower(): h for h in headers}
        for field, entry in canon_map.items():
            for alias in (entry.get("aliases") or []):
                if alias.lower() in headers_lower_map:
                    suggested[field] = headers_lower_map[alias.lower()]
                    break
        best["suggested_mapping"] = suggested
        return best

    return None


# ---------------------------------------------------------------------------
# Convert wizard selection → pipeline-compatible mapping dict
# ---------------------------------------------------------------------------

def wizard_to_pipeline_mapping(
    canonical_map: dict[str, str | None],
    bank_name: str,
    bank_key: str,
    account_name: str,
    account_id: str,
    date_format: str | None = None,
    currency_default: str = "USD",
    drop_columns: list[str] | None = None,
    locale: dict | None = None,
    cc_polarity: str | None = None,
    category_override: str | None = None,
) -> dict[str, Any]:
    """
    Build a pipeline-compatible mapping dict from wizard field selections.

    The returned dict is structurally identical to what load_mapping() returns
    from a YAML file, and can be passed directly to run_with_options(mapping_dict=...).

    cc_polarity: 'format_a' (positive=spending) or 'format_b' (positive=payment).
                 Only relevant for credit-card single-column (cc_amount) imports.
    """
    def col(field: str) -> str | None:
        return canonical_map.get(field) or None

    amount_mode = infer_amount_mode(canonical_map)

    # column_map: source_csv_header → canonical_name (first writer wins; used for extra-cols logic)
    # text_cols: canonical_name → source_csv_header (allows many canonicals → same CSV col)
    col_map:   dict[str, str] = {}
    text_cols: dict[str, str] = {}
    for wizard_field, canon_name in [
        ("description", "description"),
        ("merchant",    "merchant"),
        ("category",    "category"),
        ("notes",       "notes"),
        ("currency",    "currency"),
    ]:
        csv_col = col(wizard_field)
        if csv_col:
            text_cols[canon_name] = csv_col          # always set; many-to-one is fine
            if csv_col not in col_map:               # first canonical wins in col_map
                col_map[csv_col] = canon_name

    date_cfg: dict[str, Any] = {
        "transaction_date": col("transaction_date"),
    }
    if col("posted_date"):
        date_cfg["posted_date"] = col("posted_date")
    if date_format:
        date_cfg["date_format"] = date_format

    # ── Amount config — map new canonical names → pipeline config keys ────
    amount_cfg: dict[str, Any] = {}
    mapped = {k for k, v in canonical_map.items() if v}

    if amount_mode == "debit_credit":
        # cc_charge+cc_payment (Format C) OR bank_debit+bank_credit OR legacy debit_amount+credit_amount
        amount_cfg["debit_col"]  = (col("cc_charge")  or col("bank_debit")  or col("debit_amount"))
        amount_cfg["credit_col"] = (col("cc_payment") or col("bank_credit") or col("credit_amount"))
    elif amount_mode == "money_in_out":
        amount_cfg["money_in_col"]  = col("money_in")
        amount_cfg["money_out_col"] = col("money_out")
    elif amount_mode == "amount_plus_flag":
        amount_cfg["amount_col"]  = col("bank_amount")
        amount_cfg["dc_flag_col"] = col("dc_flag")
    else:  # signed
        # cc_amount (Format A/B) OR bank_amount OR legacy amount
        amount_cfg["signed_amount"] = (col("cc_amount") or col("bank_amount"))

    # ── Infer cc_format for normalize.py subtype classification ───────────
    # cc_format is stored alongside amount_cfg so normalize.py can pick the
    # correct classification strategy without re-inspecting column names.
    cc_format: str | None = None
    if "cc_charge" in mapped and "cc_payment" in mapped:
        cc_format = "two_col"
    elif "cc_amount" in mapped:
        cc_format = "single_col"

    if cc_format:
        amount_cfg["cc_format"] = cc_format
    if cc_polarity and cc_format == "single_col":
        amount_cfg["cc_polarity"] = cc_polarity  # 'format_a' | 'format_b'

    return {
        "bank_key":             bank_key,
        "bank_name":            bank_name,
        "account_name":         account_name,
        "account_id":           account_id,
        "amount_format_family": amount_mode,
        "column_map":           col_map,
        "text_cols":            text_cols,   # canonical→csv; survives same-column sharing
        "date":                 date_cfg,
        "amount":               amount_cfg,
        "currency_default":     currency_default,
        "drop_columns":         list(drop_columns or []),
        "locale":               locale or {},
        "category_override":    category_override,  # str | None — letters only
    }


# ---------------------------------------------------------------------------
# List all saved wizard profiles (for UI picker)
# ---------------------------------------------------------------------------

def list_wizard_profiles(profiles_dir: Path) -> list[dict[str, Any]]:
    """Return summary dicts for all saved wizard profiles."""
    if not profiles_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for yaml_path in sorted(profiles_dir.rglob("*.yaml")):
        try:
            with open(yaml_path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            for prof_name in (doc.get("profiles") or {}):
                results.append({
                    "institution":  doc.get("institution", ""),
                    "account_id":   doc.get("account_id",  ""),
                    "account_name": doc.get("account_name", ""),
                    "bank_name":    doc.get("bank_name", ""),
                    "profile_name": prof_name,
                    "yaml_path":    str(yaml_path),
                })
        except Exception:
            continue
    return results
