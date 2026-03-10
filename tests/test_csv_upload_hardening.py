"""Tests for the hardened CSV upload pipeline.

Covers all 6 cases from the CSV upload hardening task:
  1. Uppercase extension (.CSV)
  2. Wrong encoding (Latin-1, UTF-16)
  3. BOM characters (UTF-8-BOM, UTF-16 BOM)
  4. Windows line endings (\\r\\n)
  5. Non-comma delimiters (; \\t |)
  6. Excel file disguised as .csv
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from finance_etl.utils.csv_sniff import (
    _sniff_delimiter,
    _strip_bom,
    detect_encoding,
    sanitize_csv_encoding,
    sniff_csv,
    validate_uploaded_file,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_csv(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.write_text(text, encoding=encoding, newline="")


def _write_bytes(path: Path, data: bytes) -> None:
    path.write_bytes(data)


# ── Case 1: Uppercase extension ─────────────────────────────────────────────

class TestUppercaseExtension:
    def test_csv_lowercase_accepted(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        validate_uploaded_file(f, "report.csv")  # should not raise

    def test_csv_uppercase_accepted(self, tmp_path: Path):
        f = tmp_path / "data.CSV"
        f.write_text("a,b\n1,2\n")
        validate_uploaded_file(f, "REPORT.CSV")  # should not raise

    def test_csv_mixed_case_accepted(self, tmp_path: Path):
        f = tmp_path / "data.Csv"
        f.write_text("a,b\n1,2\n")
        validate_uploaded_file(f, "Data.Csv")  # should not raise

    def test_non_csv_rejected(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("a,b\n1,2\n")
        with pytest.raises(ValueError, match="Unsupported file type"):
            validate_uploaded_file(f, "data.txt")

    def test_xlsx_extension_rejected(self, tmp_path: Path):
        f = tmp_path / "data.xlsx"
        f.write_text("fake")
        with pytest.raises(ValueError, match="Unsupported file type"):
            validate_uploaded_file(f, "report.xlsx")


# ── Case 2: Wrong encoding ──────────────────────────────────────────────────

class TestWrongEncoding:
    def test_latin1_detected_and_sanitized(self, tmp_path: Path):
        f = tmp_path / "latin.csv"
        text = "Name,City\nJosé,São Paulo\nÜber,München\n"
        f.write_bytes(text.encode("latin-1"))

        original_enc = sanitize_csv_encoding(f)
        # After sanitization, file should be valid UTF-8
        content = f.read_text(encoding="utf-8")
        assert "José" in content
        assert "São Paulo" in content

    def test_utf16_detected_and_sanitized(self, tmp_path: Path):
        f = tmp_path / "utf16.csv"
        text = "Date,Amount\n2024-01-01,100.50\n"
        f.write_bytes(text.encode("utf-16"))

        sanitize_csv_encoding(f)
        content = f.read_text(encoding="utf-8")
        assert "Date" in content
        assert "100.50" in content

    def test_detect_encoding_returns_usable_codec(self, tmp_path: Path):
        """detect_encoding should return a codec Python can actually use."""
        f = tmp_path / "ascii.csv"
        f.write_text("col1,col2\n" + "a,b\n" * 1000)
        enc = detect_encoding(f)
        # Whatever chardet returns, it must be a valid Python codec
        "hello".encode(enc)  # should not raise LookupError


# ── Case 3: BOM characters ──────────────────────────────────────────────────

class TestBomHandling:
    def test_utf8_bom_stripped(self, tmp_path: Path):
        f = tmp_path / "bom.csv"
        f.write_bytes(b"\xef\xbb\xbfDate,Amount\n2024-01-01,50\n")

        sanitize_csv_encoding(f)
        content = f.read_text(encoding="utf-8")
        # BOM should be gone — first character should be 'D'
        assert content[0] == "D"
        assert not content.startswith("\ufeff")

    def test_utf16le_bom_stripped(self, tmp_path: Path):
        f = tmp_path / "bom16le.csv"
        text = "Date,Amount\n2024-01-01,99\n"
        # UTF-16-LE with BOM
        f.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))

        sanitize_csv_encoding(f)
        content = f.read_text(encoding="utf-8")
        assert content.startswith("Date")
        assert "99" in content

    def test_utf16be_bom_stripped(self, tmp_path: Path):
        f = tmp_path / "bom16be.csv"
        text = "Date,Amount\n2024-01-01,77\n"
        f.write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))

        sanitize_csv_encoding(f)
        content = f.read_text(encoding="utf-8")
        assert content.startswith("Date")
        assert "77" in content

    def test_strip_bom_function(self):
        assert _strip_bom("\ufeffHello") == "Hello"
        assert _strip_bom("Hello") == "Hello"
        assert _strip_bom("") == ""

    def test_sniff_csv_strips_bom_from_headers(self, tmp_path: Path):
        f = tmp_path / "bom_header.csv"
        f.write_bytes(b"\xef\xbb\xbfDate,Amount\n2024-01-01,100\n")

        result = sniff_csv(f)
        # The first header should NOT have the BOM character
        assert result["headers"][0] == "Date"


# ── Case 4: Windows line endings ────────────────────────────────────────────

class TestWindowsLineEndings:
    def test_crlf_normalized(self, tmp_path: Path):
        f = tmp_path / "crlf.csv"
        f.write_bytes(b"Date,Amount\r\n2024-01-01,100\r\n2024-01-02,200\r\n")

        sanitize_csv_encoding(f)
        content = f.read_bytes()
        assert b"\r\n" not in content
        assert b"\n" in content

    def test_lone_cr_normalized(self, tmp_path: Path):
        f = tmp_path / "cr.csv"
        f.write_bytes(b"Date,Amount\r2024-01-01,100\r2024-01-02,200\r")

        sanitize_csv_encoding(f)
        content = f.read_bytes()
        assert b"\r" not in content

    def test_mixed_line_endings(self, tmp_path: Path):
        f = tmp_path / "mixed.csv"
        f.write_bytes(b"Date,Amount\r\n2024-01-01,100\n2024-01-02,200\r")

        sanitize_csv_encoding(f)
        content = f.read_text(encoding="utf-8")
        lines = content.split("\n")
        assert lines[0].strip() == "Date,Amount"
        assert len([l for l in lines if l.strip()]) == 3


# ── Case 5: Non-comma delimiters ────────────────────────────────────────────

class TestNonCommaDelimiters:
    def test_semicolon_detected(self, tmp_path: Path):
        f = tmp_path / "semi.csv"
        f.write_text("Date;Amount;Category\n2024-01-01;100;Food\n2024-01-02;50;Gas\n")

        result = sniff_csv(f)
        assert result["delimiter"] == ";"
        assert result["headers"] == ["Date", "Amount", "Category"]

    def test_tab_detected(self, tmp_path: Path):
        f = tmp_path / "tab.csv"
        f.write_text("Date\tAmount\tCategory\n2024-01-01\t100\tFood\n2024-01-02\t50\tGas\n")

        result = sniff_csv(f)
        assert result["delimiter"] == "\t"
        assert result["headers"] == ["Date", "Amount", "Category"]

    def test_pipe_detected(self, tmp_path: Path):
        f = tmp_path / "pipe.csv"
        f.write_text("Date|Amount|Category\n2024-01-01|100|Food\n2024-01-02|50|Gas\n")

        result = sniff_csv(f)
        assert result["delimiter"] == "|"
        assert result["headers"] == ["Date", "Amount", "Category"]

    def test_sniff_delimiter_fallback(self):
        """When Sniffer fails, the heuristic fallback should pick the right delimiter."""
        # Construct a sample that Sniffer might struggle with but is clearly semicolon
        sample = "a;b;c\n1;2;3\n4;5;6\n7;8;9\n"
        delim = _sniff_delimiter(sample)
        assert delim == ";"

    def test_sniff_delimiter_comma_default(self):
        """Single-column data should fall back to comma."""
        sample = "value\n1\n2\n3\n"
        delim = _sniff_delimiter(sample)
        assert delim == ","


# ── Case 6: Excel file disguised as CSV ──────────────────────────────────────

class TestExcelDetection:
    def test_xls_magic_rejected(self, tmp_path: Path):
        f = tmp_path / "fake.csv"
        # OLE2 magic bytes + padding
        _write_bytes(f, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)

        with pytest.raises(ValueError, match="Excel file.*\\.xls"):
            validate_uploaded_file(f, "report.csv")

    def test_xlsx_magic_rejected(self, tmp_path: Path):
        f = tmp_path / "fake.csv"
        # ZIP/OOXML magic bytes + padding
        _write_bytes(f, b"PK\x03\x04" + b"\x00" * 100)

        with pytest.raises(ValueError, match="Excel file.*\\.xlsx"):
            validate_uploaded_file(f, "data.csv")

    def test_real_csv_not_rejected(self, tmp_path: Path):
        f = tmp_path / "real.csv"
        f.write_text("Date,Amount\n2024-01-01,100\n")

        # Should not raise
        validate_uploaded_file(f, "real.csv")


# ── Integration: full pipeline ───────────────────────────────────────────────

class TestFullPipeline:
    """End-to-end: validate → sanitize → sniff → read."""

    def test_latin1_semicolon_crlf_bom(self, tmp_path: Path):
        """A Latin-1 file with semicolons, CRLF, and a BOM-like start."""
        f = tmp_path / "complex.csv"
        text = "Datum;Betrag;Kategorie\r\n2024-01-01;100,50;Lebensmittel\r\n2024-01-02;50,75;Bücher\r\n"
        f.write_bytes(text.encode("latin-1"))

        # Validate
        validate_uploaded_file(f, "complex.csv")

        # Sanitize
        sanitize_csv_encoding(f)

        # Sniff
        result = sniff_csv(f)
        assert result["delimiter"] == ";"
        assert "Datum" in result["headers"]
        assert result["row_count_estimate"] == 2

        # Verify content is now UTF-8
        content = f.read_text(encoding="utf-8")
        assert "Bücher" in content
        assert "\r" not in content
