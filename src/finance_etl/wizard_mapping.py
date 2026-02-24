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
        debit_amount:
          aliases: ["Debit Amount", "Withdrawals"]
        credit_amount:
          aliases: ["Credit Amount", "Deposits"]
        description:
          aliases: ["Description", "Details"]
      date_format: "%m/%d/%Y"
      currency_default: USD
      drop_columns: []
      created_at: "2026-02-24T07:00:00+00:00"
      updated_at: "2026-02-24T07:00:00+00:00"

Alias arrays are always APPENDED (case-insensitive dedup); never deleted.
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

CANONICAL_FIELDS: list[str] = [
    # Required
    "transaction_date",
    # Amount (at least one group below is required)
    "debit_amount",    # pair with credit_amount → debit_credit family
    "credit_amount",
    "amount",          # alone → signed; or with dc_flag → amount_plus_flag
    "money_in",        # pair with money_out → money_in_out family
    "money_out",
    "dc_flag",         # combined with amount → amount_plus_flag family
    # Optional
    "description",
    "posted_date",
    "merchant",
    "category",
    "account",
    "notes",
    "currency",
]

REQUIRED_FIELDS: set[str] = {"transaction_date"}

# Any one of these groups fully present → valid amount mapping
AMOUNT_GROUPS: list[set[str]] = [
    {"debit_amount", "credit_amount"},
    {"money_in", "money_out"},
    {"amount"},
]

# Labels shown in the wizard UI
CANONICAL_LABELS: dict[str, str] = {
    "transaction_date": "Transaction Date *",
    "posted_date":      "Posted / Settlement Date",
    "debit_amount":     "Debit / Withdrawal Amount",
    "credit_amount":    "Credit / Deposit Amount",
    "amount":           "Amount (signed or unsigned)",
    "money_in":         "Money In",
    "money_out":        "Money Out",
    "dc_flag":          "Debit/Credit Flag",
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
    "debit_amount": [
        "debit", "debitamount", "debitamt", "withdrawal", "withdrawals", "dr",
    ],
    "credit_amount": [
        "credit", "creditamount", "creditamt", "deposit", "deposits", "cr",
    ],
    "amount": [
        "amount", "amt", "transactionamount", "txnamount", "net",
    ],
    "money_in": [
        "moneyin", "moneyreceived", "income", "received",
    ],
    "money_out": [
        "moneyout", "moneyspent", "spent", "payment", "payments",
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


def suggest_mappings(headers: list[str]) -> dict[str, str | None]:
    """
    Return {canonical_field: best_csv_header} suggestions via keyword matching.

    Each canonical field gets at most one suggestion; each CSV header is used
    for at most one canonical field (first-match wins).
    """
    used_headers: set[str] = set()
    result: dict[str, str | None] = {f: None for f in CANONICAL_FIELDS}

    for header in headers:
        canonical = _suggest_canonical_for_header(header)
        if canonical and result.get(canonical) is None and header not in used_headers:
            result[canonical] = header
            used_headers.add(header)

    return result


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

def extract_csv_headers(
    file_path: str | Path,
    max_sample_rows: int = 5,
) -> dict[str, Any]:
    """
    Detect encoding, delimiter, and headers from a CSV file.

    Returns:
      {
        "headers":            list[str],
        "sample_rows":        list[dict[str, str]],
        "encoding":           str,
        "delimiter":          str,
        "row_count_estimate": int,
        "suggestions":        dict[str, str | None],
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

    return {
        "headers":            headers,
        "sample_rows":        sample_rows,
        "encoding":           encoding,
        "delimiter":          delimiter,
        "row_count_estimate": row_count,
        "suggestions":        suggest_mappings(headers),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_wizard_mapping(
    canonical_map: dict[str, str | None],
) -> list[str]:
    """
    Check that the wizard mapping satisfies minimum requirements.

    Returns a list of human-readable error strings (empty list = OK).
    """
    errors: list[str] = []

    if not canonical_map.get("transaction_date"):
        errors.append(
            "transaction_date is required — select the column containing the transaction date."
        )

    mapped = {k for k, v in canonical_map.items() if v}
    if not any(group <= mapped for group in AMOUNT_GROUPS):
        errors.append(
            "Amount mapping is required. Map one of: "
            "(debit_amount + credit_amount), (money_in + money_out), or (amount)."
        )

    return errors


def infer_amount_mode(canonical_map: dict[str, str | None]) -> str:
    """Infer the pipeline amount_format_family from selected canonical fields."""
    mapped = {k for k, v in canonical_map.items() if v}
    if "debit_amount" in mapped and "credit_amount" in mapped:
        return "debit_credit"
    if "money_in" in mapped and "money_out" in mapped:
        return "money_in_out"
    if "amount" in mapped and "dc_flag" in mapped:
        return "amount_plus_flag"
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
) -> dict[str, Any]:
    """
    Build a pipeline-compatible mapping dict from wizard field selections.

    The returned dict is structurally identical to what load_mapping() returns
    from a YAML file, and can be passed directly to run_with_options(mapping_dict=...).
    """
    def col(field: str) -> str | None:
        return canonical_map.get(field) or None

    amount_mode = infer_amount_mode(canonical_map)

    # column_map: source_csv_header → canonical_name
    # (only the fields pipeline._build_stage_row understands)
    col_map: dict[str, str] = {}
    for wizard_field, canon_name in [
        ("description", "description"),
        ("merchant",    "merchant"),
        ("category",    "category"),
        ("notes",       "notes"),
        ("currency",    "currency"),
    ]:
        csv_col = col(wizard_field)
        if csv_col:
            col_map[csv_col] = canon_name

    date_cfg: dict[str, Any] = {
        "transaction_date": col("transaction_date"),
    }
    if col("posted_date"):
        date_cfg["posted_date"] = col("posted_date")
    if date_format:
        date_cfg["date_format"] = date_format

    amount_cfg: dict[str, Any] = {}
    if amount_mode == "debit_credit":
        amount_cfg["debit_col"]  = col("debit_amount")
        amount_cfg["credit_col"] = col("credit_amount")
    elif amount_mode == "money_in_out":
        amount_cfg["money_in_col"]  = col("money_in")
        amount_cfg["money_out_col"] = col("money_out")
    elif amount_mode == "amount_plus_flag":
        amount_cfg["amount_col"]  = col("amount")
        amount_cfg["dc_flag_col"] = col("dc_flag")
    else:  # signed
        amount_cfg["signed_amount"] = col("amount")

    return {
        "bank_key":             bank_key,
        "bank_name":            bank_name,
        "account_name":         account_name,
        "account_id":           account_id,
        "amount_format_family": amount_mode,
        "column_map":           col_map,
        "date":                 date_cfg,
        "amount":               amount_cfg,
        "currency_default":     currency_default,
        "drop_columns":         list(drop_columns or []),
        "locale":               locale or {},
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
