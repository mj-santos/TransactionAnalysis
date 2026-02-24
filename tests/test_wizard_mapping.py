"""
Unit tests for wizard_mapping.py.

Covers:
  - Header extraction
  - Canonical field suggestions
  - Mapping validation (missing date, missing amount)
  - YAML merge: new profile creation, alias append, dedup
  - find_matching_profile: match + no-match
  - wizard_to_pipeline_mapping: signed, debit_credit, money_in_out
  - infer_amount_mode
"""
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from finance_etl.wizard_mapping import (
    CANONICAL_FIELDS,
    extract_csv_headers,
    find_matching_profile,
    infer_amount_mode,
    list_wizard_profiles,
    load_wizard_profile,
    merge_wizard_profile,
    save_wizard_profile,
    suggest_mappings,
    validate_wizard_mapping,
    wizard_to_pipeline_mapping,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
NONSTANDARD_CSV = FIXTURES / "nonstandard_headers.csv"
STANDARD_CSV    = FIXTURES / "standard_headers.csv"


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------

class TestExtractCsvHeaders:
    def test_returns_headers(self):
        result = extract_csv_headers(NONSTANDARD_CSV)
        assert result["headers"] == ["Posting Date", "Narrative", "Withdrawals", "Deposits", "Balance"]

    def test_returns_sample_rows(self):
        result = extract_csv_headers(NONSTANDARD_CSV)
        assert len(result["sample_rows"]) > 0
        assert "Narrative" in result["sample_rows"][0]

    def test_returns_encoding(self):
        result = extract_csv_headers(NONSTANDARD_CSV)
        assert result["encoding"] is not None

    def test_returns_delimiter(self):
        result = extract_csv_headers(NONSTANDARD_CSV)
        assert result["delimiter"] == ","

    def test_returns_row_count(self):
        result = extract_csv_headers(NONSTANDARD_CSV)
        assert result["row_count_estimate"] == 5

    def test_returns_suggestions_dict(self):
        result = extract_csv_headers(NONSTANDARD_CSV)
        assert isinstance(result["suggestions"], dict)
        # All canonical fields should be present as keys
        for field in CANONICAL_FIELDS:
            assert field in result["suggestions"]

    def test_standard_csv_headers(self):
        result = extract_csv_headers(STANDARD_CSV)
        assert "Transaction Date" in result["headers"]
        assert "Amount" in result["headers"]


# ---------------------------------------------------------------------------
# Suggestions / fuzzy matching
# ---------------------------------------------------------------------------

class TestSuggestMappings:
    def test_nonstandard_date_header(self):
        result = suggest_mappings(["Posting Date", "Narrative", "Withdrawals", "Deposits"])
        # "Posting Date" should map to either posted_date or transaction_date
        assert result.get("posted_date") == "Posting Date" or result.get("transaction_date") == "Posting Date"

    def test_debit_credit_headers(self):
        result = suggest_mappings(["Transaction Date", "Description", "Debit Amount", "Credit Amount"])
        assert result["debit_amount"] == "Debit Amount"
        assert result["credit_amount"] == "Credit Amount"

    def test_signed_amount_header(self):
        result = suggest_mappings(["Date", "Memo", "Amount"])
        assert result["amount"] == "Amount"

    def test_description_variants(self):
        for col in ["Description", "Narrative", "Memo", "Payee"]:
            r = suggest_mappings([col])
            assert r["description"] == col, f"Expected 'description' for header '{col}'"

    def test_no_match_returns_none(self):
        result = suggest_mappings(["XYZ_TOTALLY_UNKNOWN"])
        # No canonical field should be suggested
        matched = [v for v in result.values() if v]
        assert matched == []

    def test_each_header_used_at_most_once(self):
        headers = ["Amount", "Transaction Date", "Description"]
        result = suggest_mappings(headers)
        used = [v for v in result.values() if v]
        assert len(used) == len(set(used)), "Same header used for multiple canonical fields"

    def test_standard_csv_all_fields_detected(self):
        result = suggest_mappings(["Transaction Date", "Post Date", "Description", "Amount"])
        assert result["transaction_date"] == "Transaction Date"
        assert result["posted_date"] == "Post Date"
        assert result["description"] == "Description"
        assert result["amount"] == "Amount"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateWizardMapping:
    def test_valid_signed(self):
        mapping = {"transaction_date": "Date", "amount": "Amount"}
        errors = validate_wizard_mapping(mapping)
        assert errors == []

    def test_valid_debit_credit(self):
        mapping = {
            "transaction_date": "Posting Date",
            "debit_amount":     "Withdrawals",
            "credit_amount":    "Deposits",
        }
        errors = validate_wizard_mapping(mapping)
        assert errors == []

    def test_valid_money_in_out(self):
        mapping = {
            "transaction_date": "Date",
            "money_in":         "Money In",
            "money_out":        "Money Out",
        }
        errors = validate_wizard_mapping(mapping)
        assert errors == []

    def test_missing_transaction_date_raises_error(self):
        mapping = {"amount": "Amount"}
        errors = validate_wizard_mapping(mapping)
        assert any("transaction_date" in e for e in errors)

    def test_missing_amount_raises_error(self):
        mapping = {"transaction_date": "Date"}
        errors = validate_wizard_mapping(mapping)
        assert any("amount" in e.lower() for e in errors)

    def test_partial_debit_credit_raises_error(self):
        # Only debit_amount, no credit_amount → not a complete amount group
        mapping = {"transaction_date": "Date", "debit_amount": "Withdrawals"}
        errors = validate_wizard_mapping(mapping)
        assert any("amount" in e.lower() for e in errors)

    def test_none_values_treated_as_unmapped(self):
        mapping = {"transaction_date": None, "amount": "Amount"}
        errors = validate_wizard_mapping(mapping)
        assert any("transaction_date" in e for e in errors)

    def test_empty_string_treated_as_unmapped(self):
        mapping = {"transaction_date": "", "amount": "Amount"}
        errors = validate_wizard_mapping(mapping)
        assert any("transaction_date" in e for e in errors)


# ---------------------------------------------------------------------------
# infer_amount_mode
# ---------------------------------------------------------------------------

class TestInferAmountMode:
    def test_signed(self):
        assert infer_amount_mode({"transaction_date": "Date", "amount": "Amt"}) == "signed"

    def test_debit_credit(self):
        mapping = {"transaction_date": "Date", "debit_amount": "DR", "credit_amount": "CR"}
        assert infer_amount_mode(mapping) == "debit_credit"

    def test_money_in_out(self):
        mapping = {"transaction_date": "Date", "money_in": "In", "money_out": "Out"}
        assert infer_amount_mode(mapping) == "money_in_out"

    def test_amount_plus_flag(self):
        mapping = {"transaction_date": "Date", "amount": "Amt", "dc_flag": "DR/CR"}
        assert infer_amount_mode(mapping) == "amount_plus_flag"


# ---------------------------------------------------------------------------
# YAML merge — additive profile persistence
# ---------------------------------------------------------------------------

class TestMergeWizardProfile:
    def _base_mapping(self):
        return {
            "transaction_date": "Transaction Date",
            "debit_amount":     "Debit Amount",
            "credit_amount":    "Credit Amount",
            "description":      "Narrative",
        }

    def test_creates_new_profile_when_no_existing(self):
        result = merge_wizard_profile(
            existing=None,
            institution="chase",
            account_id="checking_1234",
            account_name="My Checking",
            bank_name="Chase Bank",
            profile_name="default",
            canonical_map=self._base_mapping(),
            amount_mode="debit_credit",
            date_format="%m/%d/%Y",
        )
        assert result["institution"] == "chase"
        assert "default" in result["profiles"]
        assert result["profiles"]["default"]["amount_mode"] == "debit_credit"
        canon = result["profiles"]["default"]["canonical_map"]
        assert "Transaction Date" in canon["transaction_date"]["aliases"]
        assert "Debit Amount"     in canon["debit_amount"]["aliases"]

    def test_appends_new_alias_to_existing_field(self):
        # First merge: save "Transaction Date"
        first = merge_wizard_profile(
            existing=None,
            institution="mybank",
            account_id="acc1",
            account_name="",
            bank_name="My Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Transaction Date", "amount": "Amount"},
            amount_mode="signed",
            date_format=None,
        )
        # Second merge: add alias "Posting Date" for transaction_date
        second = merge_wizard_profile(
            existing=first,
            institution="mybank",
            account_id="acc1",
            account_name="",
            bank_name="My Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Posting Date", "amount": "Amount"},
            amount_mode="signed",
            date_format=None,
        )
        aliases = second["profiles"]["default"]["canonical_map"]["transaction_date"]["aliases"]
        assert "Transaction Date" in aliases, "Old alias must be preserved"
        assert "Posting Date"     in aliases, "New alias must be appended"

    def test_does_not_duplicate_alias_case_insensitive(self):
        first = merge_wizard_profile(
            existing=None,
            institution="bank",
            account_id="a",
            account_name="",
            bank_name="Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Transaction Date", "amount": "Amount"},
            amount_mode="signed",
            date_format=None,
        )
        # Same alias, different case
        second = merge_wizard_profile(
            existing=first,
            institution="bank",
            account_id="a",
            account_name="",
            bank_name="Bank",
            profile_name="default",
            canonical_map={"transaction_date": "TRANSACTION DATE", "amount": "Amount"},
            amount_mode="signed",
            date_format=None,
        )
        aliases = second["profiles"]["default"]["canonical_map"]["transaction_date"]["aliases"]
        count = sum(1 for a in aliases if a.lower() == "transaction date")
        assert count == 1, "Duplicate alias (case-insensitive) must not be added"

    def test_unmapped_fields_preserve_existing_aliases(self):
        """If user leaves a field as (none), existing aliases are not deleted."""
        first = merge_wizard_profile(
            existing=None,
            institution="bank",
            account_id="a",
            account_name="",
            bank_name="Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Date", "amount": "Amount", "description": "Memo"},
            amount_mode="signed",
            date_format=None,
        )
        second = merge_wizard_profile(
            existing=first,
            institution="bank",
            account_id="a",
            account_name="",
            bank_name="Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Date", "amount": "Amount", "description": None},
            amount_mode="signed",
            date_format=None,
        )
        # description aliases should still contain "Memo"
        aliases = second["profiles"]["default"]["canonical_map"]["description"]["aliases"]
        assert "Memo" in aliases

    def test_multiple_profiles_per_account(self):
        first = merge_wizard_profile(
            existing=None,
            institution="bank",
            account_id="a",
            account_name="",
            bank_name="Bank",
            profile_name="profile_a",
            canonical_map={"transaction_date": "Date A", "amount": "Amt A"},
            amount_mode="signed",
            date_format=None,
        )
        second = merge_wizard_profile(
            existing=first,
            institution="bank",
            account_id="a",
            account_name="",
            bank_name="Bank",
            profile_name="profile_b",
            canonical_map={"transaction_date": "Date B", "amount": "Amt B"},
            amount_mode="signed",
            date_format=None,
        )
        assert "profile_a" in second["profiles"]
        assert "profile_b" in second["profiles"]


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoadProfile:
    def test_round_trip(self, tmp_path):
        profile = merge_wizard_profile(
            existing=None,
            institution="testbank",
            account_id="chk001",
            account_name="Test Checking",
            bank_name="Test Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Date", "amount": "Amount"},
            amount_mode="signed",
            date_format="%m/%d/%Y",
        )
        saved_path = save_wizard_profile(tmp_path, profile)
        assert saved_path.exists()

        loaded = load_wizard_profile(tmp_path, "testbank", "chk001")
        assert loaded is not None
        assert loaded["institution"] == "testbank"
        assert "default" in loaded["profiles"]

    def test_load_nonexistent_returns_none(self, tmp_path):
        result = load_wizard_profile(tmp_path, "nobody", "noone")
        assert result is None


# ---------------------------------------------------------------------------
# find_matching_profile
# ---------------------------------------------------------------------------

class TestFindMatchingProfile:
    def _save_test_profile(self, tmp_path: Path, headers: list[str], institution: str = "bank") -> None:
        mapping = {f: headers[i] if i < len(headers) else None
                   for i, f in enumerate(["transaction_date", "amount", "description"])}
        profile = merge_wizard_profile(
            existing=None,
            institution=institution,
            account_id="acc1",
            account_name="Acc",
            bank_name="Bank",
            profile_name="default",
            canonical_map=mapping,
            amount_mode="signed",
            date_format=None,
        )
        save_wizard_profile(tmp_path, profile)

    def test_finds_exact_match(self, tmp_path: Path):
        self._save_test_profile(tmp_path, ["Transaction Date", "Amount", "Description"])
        result = find_matching_profile(
            ["Transaction Date", "Amount", "Description"],
            tmp_path,
            match_threshold=0.6,
        )
        assert result is not None
        assert result["score"] >= 0.9

    def test_no_match_below_threshold(self, tmp_path: Path):
        self._save_test_profile(tmp_path, ["Transaction Date", "Amount", "Description"])
        result = find_matching_profile(
            ["Totally", "Different", "Headers"],
            tmp_path,
            match_threshold=0.6,
        )
        assert result is None

    def test_partial_match_above_threshold(self, tmp_path: Path):
        self._save_test_profile(tmp_path, ["Transaction Date", "Amount", "Description"])
        # 2 out of 3 headers match → score = 0.67
        result = find_matching_profile(
            ["Transaction Date", "Amount", "OtherCol"],
            tmp_path,
            match_threshold=0.6,
        )
        assert result is not None
        assert result["score"] >= 0.6

    def test_returns_suggested_mapping(self, tmp_path: Path):
        self._save_test_profile(tmp_path, ["Transaction Date", "Amount", "Description"])
        result = find_matching_profile(
            ["Transaction Date", "Amount", "Description"],
            tmp_path,
        )
        assert result is not None
        assert "suggested_mapping" in result
        assert result["suggested_mapping"].get("transaction_date") == "Transaction Date"

    def test_empty_profiles_dir_returns_none(self, tmp_path: Path):
        result = find_matching_profile(["Date"], tmp_path)
        assert result is None

    def test_nonexistent_profiles_dir_returns_none(self, tmp_path: Path):
        result = find_matching_profile(["Date"], tmp_path / "does_not_exist")
        assert result is None


# ---------------------------------------------------------------------------
# wizard_to_pipeline_mapping
# ---------------------------------------------------------------------------

class TestWizardToPipelineMapping:
    def _base_kwargs(self, canonical_map):
        return dict(
            canonical_map=canonical_map,
            bank_name="Test Bank",
            bank_key="test_bank",
            account_name="Checking",
            account_id="chk001",
        )

    def test_signed_mapping(self):
        cm = {"transaction_date": "Date", "amount": "Amount", "description": "Memo"}
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        assert result["amount_format_family"] == "signed"
        assert result["amount"]["signed_amount"] == "Amount"
        assert result["date"]["transaction_date"] == "Date"
        assert result["column_map"]["Memo"] == "description"

    def test_debit_credit_mapping(self):
        cm = {
            "transaction_date": "Date",
            "debit_amount":     "Debit",
            "credit_amount":    "Credit",
        }
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        assert result["amount_format_family"] == "debit_credit"
        assert result["amount"]["debit_col"]  == "Debit"
        assert result["amount"]["credit_col"] == "Credit"

    def test_money_in_out_mapping(self):
        cm = {
            "transaction_date": "Date",
            "money_in":         "In",
            "money_out":        "Out",
        }
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        assert result["amount_format_family"] == "money_in_out"
        assert result["amount"]["money_in_col"]  == "In"
        assert result["amount"]["money_out_col"] == "Out"

    def test_amount_plus_flag_mapping(self):
        cm = {
            "transaction_date": "Date",
            "amount":           "Amt",
            "dc_flag":          "DR/CR",
        }
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        assert result["amount_format_family"] == "amount_plus_flag"
        assert result["amount"]["amount_col"]  == "Amt"
        assert result["amount"]["dc_flag_col"] == "DR/CR"

    def test_posted_date_included_when_mapped(self):
        cm = {
            "transaction_date": "Date",
            "posted_date":      "Post Date",
            "amount":           "Amt",
        }
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        assert result["date"].get("posted_date") == "Post Date"

    def test_date_format_included(self):
        cm = {"transaction_date": "Date", "amount": "Amt"}
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm), date_format="%d/%m/%Y")
        assert result["date"]["date_format"] == "%d/%m/%Y"

    def test_required_keys_present(self):
        cm = {"transaction_date": "Date", "amount": "Amt"}
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        for key in ("bank_key", "bank_name", "amount_format_family", "column_map", "date", "amount"):
            assert key in result

    def test_pipeline_mapping_passes_model_validation(self):
        """The dict produced by wizard_to_pipeline_mapping must pass parse_mapping_config."""
        from finance_etl.models import parse_mapping_config
        cm = {
            "transaction_date": "Transaction Date",
            "debit_amount":     "Debit Amount",
            "credit_amount":    "Credit Amount",
            "description":      "Narrative",
        }
        result = wizard_to_pipeline_mapping(**self._base_kwargs(cm))
        # Should not raise
        mc = parse_mapping_config(result, "<test>")
        assert mc.amount_format_family == "debit_credit"


# ---------------------------------------------------------------------------
# list_wizard_profiles
# ---------------------------------------------------------------------------

class TestListWizardProfiles:
    def test_empty_dir(self, tmp_path):
        assert list_wizard_profiles(tmp_path) == []

    def test_lists_saved_profile(self, tmp_path):
        profile = merge_wizard_profile(
            existing=None,
            institution="mybank",
            account_id="acc1",
            account_name="My Acc",
            bank_name="My Bank",
            profile_name="default",
            canonical_map={"transaction_date": "Date", "amount": "Amount"},
            amount_mode="signed",
            date_format=None,
        )
        save_wizard_profile(tmp_path, profile)
        result = list_wizard_profiles(tmp_path)
        assert len(result) == 1
        assert result[0]["institution"] == "mybank"
        assert result[0]["profile_name"] == "default"
