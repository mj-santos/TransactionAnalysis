"""
Unit tests for amount parsing (all families, locales, parentheses).
Covers design_rules.txt §2 + §8.
"""
import pytest
from decimal import Decimal

from finance_etl.utils.money import (
    AmountParseError,
    parse_signed,
    parse_debit_credit,
    parse_money_in_out,
    parse_amount_plus_flag,
)


# ---------------------------------------------------------------------------
# Family A: signed
# ---------------------------------------------------------------------------
class TestParseSigned:
    def test_positive_plain(self):
        assert parse_signed("123.45") == Decimal("123.45")

    def test_negative_plain(self):
        assert parse_signed("-123.45") == Decimal("-123.45")

    def test_positive_with_dollar(self):
        assert parse_signed("$123.45") == Decimal("123.45")

    def test_negative_with_dollar(self):
        assert parse_signed("-$123.45") == Decimal("-123.45")

    def test_parentheses_negative_enabled(self):
        assert parse_signed("(123.45)", {"parentheses_negative": True}) == Decimal("-123.45")

    def test_parentheses_with_dollar_negative(self):
        assert parse_signed("($99.00)", {"parentheses_negative": True}) == Decimal("-99.00")

    def test_parentheses_not_enabled_raises(self):
        # Without parentheses_negative, "(123.45)" cannot be parsed as a number
        with pytest.raises(AmountParseError):
            parse_signed("(123.45)", {"parentheses_negative": False})

    def test_zero(self):
        assert parse_signed("0.00") == Decimal("0.00")

    def test_large_number_with_comma_thousands(self):
        result = parse_signed("1,234,567.89", {"thousands_separator": ",", "decimal_separator": "."})
        assert result == Decimal("1234567.89")

    def test_eu_locale_decimal_comma(self):
        result = parse_signed("1.234,56", {"decimal_separator": ",", "thousands_separator": "."})
        assert result == Decimal("1234.56")

    def test_empty_string_raises(self):
        with pytest.raises(AmountParseError):
            parse_signed("")

    def test_whitespace_only_raises(self):
        with pytest.raises(AmountParseError):
            parse_signed("   ")

    def test_non_numeric_raises(self):
        with pytest.raises(AmountParseError):
            parse_signed("abc")

    def test_quantized_to_two_decimals(self):
        # Input with more decimals should be quantized
        result = parse_signed("10.001")
        assert result == Decimal("10.00")

    def test_negative_zero(self):
        result = parse_signed("-0.00")
        assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# Family B: debit_credit
# ---------------------------------------------------------------------------
class TestParseDebitCredit:
    def test_debit_only(self):
        assert parse_debit_credit("50.00", None) == Decimal("-50.00")

    def test_credit_only(self):
        assert parse_debit_credit(None, "100.00") == Decimal("100.00")

    def test_debit_empty_string(self):
        assert parse_debit_credit("", "200.00") == Decimal("200.00")

    def test_credit_empty_string(self):
        assert parse_debit_credit("75.00", "") == Decimal("-75.00")

    def test_both_populated_raises(self):
        with pytest.raises(AmountParseError, match="Both debit"):
            parse_debit_credit("50.00", "50.00")

    def test_both_empty_raises(self):
        with pytest.raises(AmountParseError):
            parse_debit_credit("", "")

    def test_debit_with_currency_symbol(self):
        assert parse_debit_credit("$300.00", None) == Decimal("-300.00")

    def test_credit_with_parentheses_locale(self):
        locale = {"parentheses_negative": True}
        # credit column — abs is taken, so even with parens it should be positive
        assert parse_debit_credit(None, "(100.00)", locale) == Decimal("100.00")

    def test_eu_locale_debit(self):
        locale = {"decimal_separator": ",", "thousands_separator": "."}
        assert parse_debit_credit("1.500,00", None, locale) == Decimal("-1500.00")


# ---------------------------------------------------------------------------
# Family C: money_in_out
# ---------------------------------------------------------------------------
class TestParseMoneyInOut:
    def test_inflow_only(self):
        assert parse_money_in_out("500.00", None) == Decimal("500.00")

    def test_outflow_only(self):
        assert parse_money_in_out(None, "200.00") == Decimal("-200.00")

    def test_both_zero_raises(self):
        with pytest.raises(AmountParseError):
            parse_money_in_out("0", "0")

    def test_both_empty_raises(self):
        with pytest.raises(AmountParseError):
            parse_money_in_out("", "")

    def test_inflow_larger(self):
        assert parse_money_in_out("100.00", "30.00") == Decimal("70.00")

    def test_outflow_larger(self):
        assert parse_money_in_out("10.00", "50.00") == Decimal("-40.00")

    def test_eu_locale(self):
        locale = {"decimal_separator": ",", "thousands_separator": "."}
        assert parse_money_in_out("1.000,50", None, locale) == Decimal("1000.50")


# ---------------------------------------------------------------------------
# Family D: amount_plus_flag
# ---------------------------------------------------------------------------
class TestParseAmountPlusFlag:
    DEBIT = ["D", "DR", "Debit"]
    CREDIT = ["C", "CR", "Credit"]

    def test_debit_flag(self):
        assert parse_amount_plus_flag("100.00", "D", self.DEBIT, self.CREDIT) == Decimal("-100.00")

    def test_credit_flag(self):
        assert parse_amount_plus_flag("250.00", "C", self.DEBIT, self.CREDIT) == Decimal("250.00")

    def test_debit_flag_dr(self):
        assert parse_amount_plus_flag("99.99", "DR", self.DEBIT, self.CREDIT) == Decimal("-99.99")

    def test_credit_flag_cr(self):
        assert parse_amount_plus_flag("99.99", "CR", self.DEBIT, self.CREDIT) == Decimal("99.99")

    def test_unknown_flag_raises(self):
        with pytest.raises(AmountParseError, match="Unknown dc_flag"):
            parse_amount_plus_flag("50.00", "X", self.DEBIT, self.CREDIT)

    def test_empty_flag_raises(self):
        with pytest.raises(AmountParseError):
            parse_amount_plus_flag("50.00", "", self.DEBIT, self.CREDIT)

    def test_abs_applied_to_debit(self):
        # Even if the raw amount has a negative sign, debit should be -abs
        # i.e. no double-negative
        assert parse_amount_plus_flag("-100.00", "D", self.DEBIT, self.CREDIT) == Decimal("-100.00")

    def test_eu_locale_with_flag(self):
        locale = {"decimal_separator": ",", "thousands_separator": "."}
        result = parse_amount_plus_flag("1.500,75", "C", self.DEBIT, self.CREDIT, locale)
        assert result == Decimal("1500.75")


    def test_flag_with_whitespace(self):
        assert parse_amount_plus_flag("50.00", "  C  ", self.DEBIT, self.CREDIT) == Decimal("50.00")

    def test_empty_amount_raises(self):
        with pytest.raises(AmountParseError):
            parse_amount_plus_flag("", "D", self.DEBIT, self.CREDIT)


class TestLocalizedAndParenthesesEdgeCases:
    def test_signed_eu_parentheses_negative(self):
        locale = {"decimal_separator": ",", "thousands_separator": ".", "parentheses_negative": True}
        assert parse_signed("(1.234,56)", locale) == Decimal("-1234.56")

    def test_debit_credit_parentheses_in_debit(self):
        locale = {"parentheses_negative": True}
        assert parse_debit_credit("(123.45)", "", locale) == Decimal("-123.45")
