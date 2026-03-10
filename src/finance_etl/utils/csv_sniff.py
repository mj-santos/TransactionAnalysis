"""CSV sniffing, profiling, and upload-validation utilities."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import chardet


# ── Excel magic bytes ────────────────────────────────────────────────────────
_XLS_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE2 Compound Document
_XLSX_MAGIC = b"PK\x03\x04"                         # ZIP (OOXML)


def detect_encoding(path: str | Path, sample_bytes: int = 65_536) -> str:
    """Detect file encoding using chardet.

    Reads up to *sample_bytes* (default 64 KiB) for detection accuracy.
    Falls back to ``utf-8`` if chardet returns None.
    """
    with open(path, "rb") as f:
        raw = f.read(sample_bytes)
    result = chardet.detect(raw)
    encoding = result.get("encoding") or "utf-8"
    # chardet may report "UTF-8-SIG" for BOM-prefixed files — normalise to
    # the standard Python codec name so open() handles BOM transparently.
    if encoding.upper().replace("-", "").replace("_", "") in ("UTF8SIG", "UTF8BOM"):
        return "utf-8-sig"
    return encoding


def _strip_bom(text: str) -> str:
    """Remove a leading Unicode BOM (U+FEFF) if present."""
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _sniff_delimiter(sample: str) -> str:
    """Detect CSV delimiter with Sniffer, falling back to column-count heuristic.

    If ``csv.Sniffer`` fails or returns an improbable delimiter (e.g. a letter),
    tries each of ``,  ;  \\t  |`` and picks the one that produces the most
    consistent column count across the first 10 rows.
    """
    # Try Sniffer first — it works well on clean CSVs
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        delimiter = dialect.delimiter
        # Sanity: reject delimiters that are letters/digits (Sniffer bug)
        if delimiter.isalnum():
            raise csv.Error("unlikely delimiter")
        return delimiter
    except csv.Error:
        pass

    # Fallback: try common delimiters and pick the best one
    best_delim = ","
    best_score = -1
    for candidate in [",", ";", "\t", "|"]:
        reader = csv.reader(io.StringIO(sample), delimiter=candidate)
        counts = []
        for i, row in enumerate(reader):
            if i >= 10:
                break
            counts.append(len(row))
        if not counts or max(counts) < 2:
            continue
        # Score: how many rows match the mode column count
        mode = max(set(counts), key=counts.count)
        score = counts.count(mode) * mode  # favour more columns too
        if score > best_score:
            best_score = score
            best_delim = candidate
    return best_delim


def validate_uploaded_file(path: str | Path, original_filename: str) -> None:
    """Run all pre-parse validation on an uploaded file.

    Checks (in order):
    1. File extension is ``.csv`` (case-insensitive)
    2. File is not an Excel binary disguised as CSV (magic-byte check)

    Raises ``ValueError`` with a human-readable message on failure.
    """
    # Case 1: uppercase / wrong extension
    if not original_filename.lower().endswith(".csv"):
        raise ValueError(
            f"Unsupported file type: '{original_filename}'. "
            "Please upload a CSV file (.csv)."
        )

    # Case 6: Excel file disguised as .csv — check magic bytes
    raw_head = Path(path).read_bytes()[:8]
    if raw_head[:8] == _XLS_MAGIC:
        raise ValueError(
            "This file appears to be an Excel file (.xls). "
            "Please export it as CSV from Excel and re-upload."
        )
    if raw_head[:4] == _XLSX_MAGIC:
        raise ValueError(
            "This file appears to be an Excel file (.xlsx). "
            "Please export it as CSV from Excel and re-upload."
        )


def sanitize_csv_encoding(path: str | Path) -> str:
    """Detect encoding, strip BOM, normalise line endings, and rewrite as UTF-8.

    Returns the detected original encoding (for logging).
    The file at *path* is rewritten in-place as clean UTF-8 with ``\\n`` line
    endings and no BOM, so all downstream code can assume UTF-8.
    """
    p = Path(path)
    raw = p.read_bytes()

    # Strip byte-level BOMs before chardet (handles UTF-16 LE/BE and UTF-8)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        # UTF-16 BOM — decode accordingly, then re-encode as UTF-8
        enc = "utf-16"
    elif raw[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    else:
        result = chardet.detect(raw[:65_536])
        enc = result.get("encoding") or "utf-8"

    text = raw.decode(enc, errors="replace")

    # Strip any remaining Unicode BOM character after decoding
    text = _strip_bom(text)

    # Normalise line endings: \r\n → \n, lone \r → \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Rewrite as clean UTF-8
    p.write_text(text, encoding="utf-8", newline="")

    return enc


def sniff_csv(path: str | Path, encoding: str | None = None) -> dict[str, Any]:
    """
    Return a profile dict with delimiter, encoding, and header columns.

    Returns
    -------
    {
        "encoding": str,
        "delimiter": str,
        "headers": list[str],
        "row_count_estimate": int,   # lines minus header
    }
    """
    enc = encoding or detect_encoding(path)

    with open(path, encoding=enc, errors="replace", newline="") as f:
        sample = f.read(65_536)

    # Strip BOM so it doesn't end up in the first header name
    sample = _strip_bom(sample)
    delimiter = _sniff_delimiter(sample)

    with open(path, encoding=enc, errors="replace", newline="") as f:
        full_text = _strip_bom(f.read())

    reader = csv.reader(io.StringIO(full_text), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration:
        headers = []
    row_count = sum(1 for _ in reader)

    return {
        "encoding": enc,
        "delimiter": delimiter,
        "headers": [h.strip() for h in headers],
        "row_count_estimate": row_count,
    }
