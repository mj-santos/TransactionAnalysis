"""
Unit tests for date parsing, covering design_rules.txt §3 + §8.
"""
import datetime
import pytest

from finance_etl.utils.dates import parse_date, DateParseError


class TestParseDateISO:
    def test_iso_date(self):
        assert parse_date("2024-03-15") == datetime.date(2024, 3, 15)

    def test_iso_invalid_raises(self):
        with pytest.raises(DateParseError):
            parse_date("2024-13-01")


class TestParseDateExplicitFormat:
    def test_explicit_us_format(self):
        assert parse_date("03/15/2024", date_format="%m/%d/%Y") == datetime.date(2024, 3, 15)

    def test_explicit_eu_format(self):
        assert parse_date("15/03/2024", date_format="%d/%m/%Y") == datetime.date(2024, 3, 15)

    def test_explicit_format_mismatch_raises(self):
        with pytest.raises(DateParseError):
            parse_date("2024-03-15", date_format="%m/%d/%Y")

    def test_named_month_explicit(self):
        assert parse_date("Mar 15, 2024", date_format="%b %d, %Y") == datetime.date(2024, 3, 15)


class TestParseDateAmbigiuty:
    def test_ambiguous_no_locale_raises(self):
        """01/02/2024 could be Jan-2 (US) or Feb-1 (EU). Must fail without locale."""
        with pytest.raises(DateParseError, match="[Aa]mbiguous"):
            parse_date("01/02/2024")

    def test_ambiguous_us_locale(self):
        result = parse_date("01/02/2024", locale_cfg={"date_locale": "US"})
        assert result == datetime.date(2024, 1, 2)

    def test_ambiguous_eu_locale(self):
        result = parse_date("01/02/2024", locale_cfg={"date_locale": "EU"})
        assert result == datetime.date(2024, 2, 1)

    def test_unambiguous_day_over_12(self):
        """15/03/2024 — day=15 cannot be month, so unambiguous even without locale."""
        result = parse_date("15/03/2024")
        assert result == datetime.date(2024, 3, 15)

    def test_unambiguous_month_over_12(self):
        """03/15/2024 — month position 15 cannot be month, so unambiguous."""
        result = parse_date("03/15/2024")
        assert result == datetime.date(2024, 3, 15)


class TestParseDateEdgeCases:
    def test_empty_raises(self):
        with pytest.raises(DateParseError):
            parse_date("")

    def test_whitespace_only_raises(self):
        with pytest.raises(DateParseError):
            parse_date("   ")

    def test_garbage_raises(self):
        with pytest.raises(DateParseError):
            parse_date("not-a-date")

    def test_named_month_format(self):
        assert parse_date("Jan 5, 2023") == datetime.date(2023, 1, 5)

    def test_iso_with_leading_whitespace(self):
        assert parse_date("  2024-06-01  ") == datetime.date(2024, 6, 1)
