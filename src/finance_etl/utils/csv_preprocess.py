"""
CSV Pre-Processing — auto-detect and clean non-standard statement formats.

Pattern 1 — Header echo:
  Some CSVs include the column name as the first sub-line of each cell value.
  Detection: first data row has cells whose first line matches the column header.
  Action: strip that leading label from every row in the column.

Pattern 2 — Metadata rows above the real header:
  Some CSVs begin with non-tabular bank metadata before the column header row.
  Detection: scan from the top until a row where ≥2 cells match canonical synonyms.
  Action: discard rows above that row; preserve them as statement_meta.

Pre-processing runs automatically on every uploaded CSV before field-mapping.
If neither pattern is detected the file is returned unchanged.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from finance_etl.utils.csv_sniff import detect_encoding
from finance_etl.utils.log import get_logger

log = get_logger(__name__)

# ── Canonical field synonyms for Pattern 2 header detection ────────────────
_CANONICAL_SYNONYMS: dict[str, set[str]] = {
    "date": {
        "date", "transaction date", "trans date", "posted", "posting date",
        "transaction_date", "post date",
    },
    "amount": {
        "amount", "transaction amount", "total", "debit", "credit",
        "charge", "charges",
    },
    "description": {
        "description", "memo", "details", "merchant", "narrative",
        "transaction description", "payee", "detail",
    },
    "category": {
        "category", "type", "transaction type", "trans type",
    },
    "balance": {
        "balance", "running balance", "available balance",
    },
}
# Pre-flatten for fast lookup
_ALL_SYNONYMS: set[str] = {s for syns in _CANONICAL_SYNONYMS.values() for s in syns}


# ── Normalization ───────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def _is_canonical(cell: str) -> bool:
    return _normalize(cell.strip()) in _ALL_SYNONYMS


# ── Pattern 2: find real header row ────────────────────────────────────────

def _find_header_row(
    raw_lines: list[str], delimiter: str
) -> tuple[int, dict[str, str]]:
    """
    Scan raw lines from the top.  Return (header_row_index, statement_meta).

    header_row_index: index into raw_lines where the true header row lives.
                      0 means no metadata rows were detected.
    statement_meta:   key-value pairs extracted from pre-header metadata rows.
    """
    statement_meta: dict[str, str] = {}

    for i, line in enumerate(raw_lines[:30]):
        stripped = line.strip()
        if not stripped:
            continue

        try:
            cells = next(csv.reader(io.StringIO(stripped), delimiter=delimiter))
        except StopIteration:
            continue

        matches = sum(1 for c in cells if c.strip() and _is_canonical(c.strip()))
        if matches >= 2:
            if i > 0:
                log.info(
                    "[PreProcess] Skipped %d metadata rows. Header found at row %d. Metadata: %s",
                    i, i, statement_meta,
                )
            return i, statement_meta

        # Collect metadata from pre-header lines
        cells_s = [c.strip() for c in cells if c.strip()]
        if not cells_s:
            continue
        if len(cells_s) == 1:
            statement_meta[f"meta_{i}"] = cells_s[0]
        elif len(cells_s) == 2:
            # Treat as key: value pair
            statement_meta[cells_s[0]] = cells_s[1]
        else:
            statement_meta[f"meta_{i}"] = " | ".join(cells_s)

    return 0, {}


# ── Pattern 1: strip header echo from cell values ──────────────────────────

def _strip_header_echo(
    headers: list[str], rows: list[list[str]]
) -> list[str]:
    """
    Detect and strip leading header labels embedded in cell values.

    Returns the list of column names where stripping was applied.

    Examples
    --------
    header="Date", cell="Date\\nFeb 12 2026"    → "Feb 12 2026"
    header="Description", cell="Description\\nAMAZON" → "AMAZON"
    """
    if not rows:
        return []

    first_row = rows[0]
    cols_to_strip: list[str] = []

    for col_idx, header in enumerate(headers):
        if col_idx >= len(first_row):
            continue
        cell = first_row[col_idx]
        if not cell:
            continue

        header_norm = _normalize(header)
        if not header_norm:
            continue

        # Compare against the first line of the cell value
        first_line = cell.split("\n")[0] if "\n" in cell else cell
        if _normalize(first_line) == header_norm:
            cols_to_strip.append(header)
            log.info("[PreProcess] Stripped header echo from column: %s", header)

    if not cols_to_strip:
        return []

    strip_set = set(cols_to_strip)

    for row in rows:
        for col_idx, header in enumerate(headers):
            if header not in strip_set or col_idx >= len(row):
                continue
            cell = row[col_idx]
            header_norm = _normalize(header)

            if "\n" in cell:
                lines = cell.split("\n")
                if _normalize(lines[0]) == header_norm:
                    # Join remaining sub-lines with a space
                    row[col_idx] = " ".join(
                        ln.strip() for ln in lines[1:] if ln.strip()
                    )
            else:
                # Cell IS just the header label — clear it
                if _normalize(cell) == header_norm:
                    row[col_idx] = ""

    return cols_to_strip


# ── Public entry point ─────────────────────────────────────────────────────

def preprocess_csv(path: str | Path) -> dict[str, Any]:
    """
    Detect and auto-clean a CSV file in-place.

    Applies Pattern 2 (metadata row removal) then Pattern 1 (header echo strip).
    If neither pattern is detected, the file is left untouched.

    Returns
    -------
    {
        "patterns_applied": list[str],  # human-readable descriptions of what changed
        "metadata": dict[str, str],     # statement_meta captured from Pattern 2
        "banner": str | None,           # dismissible UI info text (None = no changes)
    }
    """
    path = Path(path)
    enc = detect_encoding(path)

    with open(path, encoding=enc, errors="replace", newline="") as fh:
        raw_lines = fh.readlines()

    if not raw_lines:
        return {"patterns_applied": [], "metadata": {}, "banner": None}

    patterns_applied: list[str] = []
    statement_meta: dict[str, str] = {}

    # ── Sniff delimiter from the first non-empty lines ──────────────────────
    sample = "".join(raw_lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    # ── Pattern 2: discard metadata rows above the real header ─────────────
    header_row_idx, statement_meta = _find_header_row(raw_lines, delimiter)
    if header_row_idx > 0:
        raw_lines = raw_lines[header_row_idx:]
        patterns_applied.append(
            f"Skipped {header_row_idx} metadata row(s); header found at row {header_row_idx}"
        )
        # Re-sniff delimiter after trimming metadata
        sample = "".join(raw_lines[:20])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
            delimiter = dialect.delimiter
        except csv.Error:
            pass

    # ── Parse cleaned lines into rows ───────────────────────────────────────
    reader = csv.reader(io.StringIO("".join(raw_lines)), delimiter=delimiter)
    all_rows = list(reader)
    if not all_rows:
        return {"patterns_applied": patterns_applied, "metadata": statement_meta, "banner": None}

    headers = [h.strip() for h in all_rows[0]]
    data_rows = [list(r) for r in all_rows[1:]]

    # ── Pattern 1: strip header echo ────────────────────────────────────────
    stripped_cols = _strip_header_echo(headers, data_rows)
    for col in stripped_cols:
        patterns_applied.append(f"Stripped header echo from column: {col}")

    # ── Write cleaned file back if anything changed ──────────────────────────
    if patterns_applied:
        with open(path, "w", encoding=enc, newline="") as fh:
            writer = csv.writer(fh, delimiter=delimiter)
            writer.writerow(headers)
            writer.writerows(data_rows)

    # ── Build UI banner ──────────────────────────────────────────────────────
    banner: str | None = None
    if patterns_applied:
        parts: list[str] = []
        if header_row_idx > 0:
            parts.append(f"{header_row_idx} metadata row(s) removed")
        if stripped_cols:
            parts.append("column labels cleaned automatically")
        banner = "Non-standard format detected. " + " and ".join(parts) + "."

    return {
        "patterns_applied": patterns_applied,
        "metadata": statement_meta,
        "banner": banner,
    }
