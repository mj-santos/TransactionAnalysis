"""CSV sniffing and profiling utilities."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import chardet


def detect_encoding(path: str | Path, sample_bytes: int = 32_768) -> str:
    """Detect file encoding using chardet."""
    with open(path, "rb") as f:
        raw = f.read(sample_bytes)
    result = chardet.detect(raw)
    return result.get("encoding") or "utf-8"


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

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","  # safe fallback

    with open(path, encoding=enc, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
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
