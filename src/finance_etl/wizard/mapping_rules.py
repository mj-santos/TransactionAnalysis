"""
Automated Mapping Rules — Regex / Keyword Generation
=====================================================

Scans a bank CSV's transaction descriptions, identifies high-frequency
vendors, and generates keyword-based mapping rules that can be written
directly into the ``keyword_rules`` section of a config.yaml.

Public functions
----------------
generate_mapping_rules(csv_path, description_col, min_occurrences, default_category)
    → dict[str, str]   {VENDOR_KEYWORD: category_name}

read_descriptions(csv_path, description_col)
    → list[str]        (also used by setup_wizard.py)
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
from typing import Optional

import chardet


# ---------------------------------------------------------------------------
# Noise-stripping patterns applied before extracting a vendor token
# ---------------------------------------------------------------------------
_STRIP_PATTERNS: list[re.Pattern] = [
    re.compile(r"\d{5,}"),            # long digit strings (ref numbers, card #s)
    re.compile(r"\b[A-Z]{2}\d+\b"),   # location codes like NY12345
    re.compile(r"\d{2}/\d{2}"),       # date fragments  MM/DD
    re.compile(r"#\d+"),              # reference numbers  #123
    re.compile(r"\*{2,}"),            # masking asterisks
]

# Words that appear in descriptions but do NOT identify a vendor.
_NOISE_WORDS: frozenset[str] = frozenset({
    "purchase", "payment", "debit", "credit", "pos", "visa", "mc", "amex",
    "mastercard", "transaction", "online", "store", "llc", "inc", "ltd",
    "corp", "co", "the", "and", "for", "of", "at", "to",
})

# Column-name substrings used to auto-detect the description column.
# "transaction" is deliberately excluded to avoid matching "Transaction Date".
_DESC_KEYWORDS = ("description", "desc", "memo", "payee", "narrative",
                  "narration", "detail", "reference", "particulars")


# ---------------------------------------------------------------------------
# CSV reading helper (shared with setup_wizard.py)
# ---------------------------------------------------------------------------

def read_descriptions(
    csv_path: str | Path,
    description_col: Optional[str] = None,
) -> list[str]:
    """
    Return all non-empty description strings from *csv_path*.

    If *description_col* is ``None`` the function tries to auto-detect the
    column by scanning headers for the substrings listed in _DESC_KEYWORDS.

    Raises
    ------
    ValueError
        If the CSV has no headers or the description column cannot be found.
    """
    path = Path(csv_path)

    # Detect encoding.
    with open(path, "rb") as fh:
        raw_bytes = fh.read(32_768)
    encoding: str = chardet.detect(raw_bytes).get("encoding") or "utf-8"

    with open(path, encoding=encoding, errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no headers: {csv_path}")

        # Auto-detect description column if not provided.
        if description_col is None:
            for col in reader.fieldnames:
                if any(kw in col.lower() for kw in _DESC_KEYWORDS):
                    description_col = col
                    break

        if description_col is None:
            raise ValueError(
                "Could not auto-detect the description column. "
                "Pass description_col= explicitly."
            )

        return [
            row[description_col]
            for row in reader
            if row.get(description_col, "").strip()
        ]


# ---------------------------------------------------------------------------
# Vendor extraction
# ---------------------------------------------------------------------------

def _extract_vendor(description: str) -> Optional[str]:
    """
    Return a normalised vendor token from a raw transaction description.

    Algorithm
    ---------
    1. Upper-case and strip outer whitespace.
    2. Remove noise patterns (dates, reference numbers, card codes).
    3. Split on whitespace; discard noise words and very short tokens.
    4. Take the first 1–2 meaningful words as the vendor identifier.
    5. Reject tokens that are purely numeric or shorter than 3 characters.
    """
    d = description.strip().upper()
    for pat in _STRIP_PATTERNS:
        d = pat.sub(" ", d)
    d = re.sub(r"\s+", " ", d).strip()

    # Strip non-alphanumeric characters from each token before filtering.
    words = [
        re.sub(r"[^A-Z0-9]", "", w) for w in d.split()
    ]
    words = [
        w for w in words
        if len(w) >= 3 and w.lower() not in _NOISE_WORDS
    ]
    if not words:
        return None

    # Use the first meaningful word as the vendor key so that variants like
    # "STARBUCKS STORE #1234" and "STARBUCKS DRIVE THRU" both map to
    # "STARBUCKS" and can be aggregated for frequency counting.
    vendor = words[0]

    # Reject purely numeric vendors.
    if re.match(r"^\d+$", vendor) or len(vendor) < 3:
        return None

    return vendor


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def generate_mapping_rules(
    csv_path: str,
    description_col: Optional[str] = None,
    min_occurrences: int = 3,
    default_category: str = "General",
) -> dict[str, str]:
    """
    Scan the transaction history in *csv_path* and generate keyword-based
    mapping rules for every vendor that appears at least *min_occurrences*
    times.

    Each generated rule maps a vendor keyword to *default_category* so the
    user can later refine the assignment in the wizard or by editing the
    config.yaml.

    Parameters
    ----------
    csv_path : str
        Path to the bank CSV file.
    description_col : str | None
        Name of the description column.  Auto-detected when ``None``.
    min_occurrences : int
        Minimum appearance count before a rule is emitted (default 3).
    default_category : str
        Category assigned to every auto-generated rule (default "General").

    Returns
    -------
    dict[str, str]
        Ordered ``{vendor_keyword: category_name}`` sorted by descending
        frequency.  Suitable for the ``keyword_rules`` section of config.yaml.
    """
    descriptions = read_descriptions(csv_path, description_col)

    vendor_counts: Counter[str] = Counter(
        v
        for v in (_extract_vendor(d) for d in descriptions)
        if v is not None
    )

    rules: dict[str, str] = {
        vendor: default_category
        for vendor, count in vendor_counts.most_common()
        if count >= min_occurrences
    }

    _print_rules(rules, vendor_counts)
    return rules


# ---------------------------------------------------------------------------
# Pretty-print helper
# ---------------------------------------------------------------------------

def _print_rules(rules: dict[str, str], counts: Counter) -> None:
    if not rules:
        print("\n=== Auto-generated Mapping Rules ===")
        print("  (no vendors exceeded the minimum occurrence threshold)")
        print("=" * 38)
        return
    print(f"\n=== Auto-generated Mapping Rules ({len(rules)} vendors) ===")
    for vendor, category in rules.items():
        print(f"  {vendor!r:35s} → {category}  (seen {counts[vendor]}×)")
    print("=" * 52)
