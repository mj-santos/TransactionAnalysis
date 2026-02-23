"""
Unit tests for mapping application.
Covers design_rules.txt §1 + §8: rename/drop/select + metadata.
"""
import pytest
import yaml
import tempfile
import os
from pathlib import Path

from finance_etl.mapping import load_mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(data: dict) -> str:
    """Write a mapping dict to a temp YAML file, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(data, f)
    f.close()
    return f.name


VALID_SIGNED = {
    "bank_key": "test_bank",
    "bank_name": "Test Bank",
    "account_name": "Checking",
    "account_id": "ACC-001",
    "amount_format_family": "signed",
    "column_map": {"Date": "transaction_date", "Desc": "description", "Amt": "amount"},
    "drop_columns": ["Balance"],
    "date": {"transaction_date": "Date"},
    "amount": {"signed_amount": "Amt"},
    "currency_default": "USD",
}

VALID_DEBIT_CREDIT = {
    "bank_key": "dc_bank",
    "bank_name": "DC Bank",
    "account_name": "Savings",
    "account_id": "SAV-999",
    "amount_format_family": "debit_credit",
    "column_map": {},
    "drop_columns": [],
    "date": {"transaction_date": "Trans Date"},
    "amount": {"debit_col": "Debit Amount", "credit_col": "Credit Amount"},
}

VALID_MONEY_IN_OUT = {
    "bank_key": "mio_bank",
    "bank_name": "MIO Bank",
    "account_name": "Current",
    "account_id": "MIO-01",
    "amount_format_family": "money_in_out",
    "column_map": {},
    "drop_columns": [],
    "date": {"transaction_date": "Value Date"},
    "amount": {"money_in_col": "Money In", "money_out_col": "Money Out"},
}

VALID_FLAG = {
    "bank_key": "flag_bank",
    "bank_name": "Flag Bank",
    "account_name": "Main",
    "account_id": "FLAGMAIN",
    "amount_format_family": "amount_plus_flag",
    "column_map": {},
    "drop_columns": [],
    "date": {"transaction_date": "TXN DATE"},
    "amount": {
        "amount_col": "TXN AMT",
        "dc_flag_col": "DR/CR",
        "dc_flag_values": {"debit": ["DR"], "credit": ["CR"]},
    },
    "locale": {"date_locale": "US"},
}


class TestLoadMappingValid:
    def test_signed_family_loads(self):
        path = write_yaml(VALID_SIGNED)
        cfg = load_mapping(path)
        assert cfg["bank_key"] == "test_bank"
        assert cfg["amount_format_family"] == "signed"
        os.unlink(path)

    def test_debit_credit_family_loads(self):
        path = write_yaml(VALID_DEBIT_CREDIT)
        cfg = load_mapping(path)
        assert cfg["amount_format_family"] == "debit_credit"
        os.unlink(path)

    def test_money_in_out_family_loads(self):
        path = write_yaml(VALID_MONEY_IN_OUT)
        cfg = load_mapping(path)
        assert cfg["amount_format_family"] == "money_in_out"
        os.unlink(path)

    def test_amount_plus_flag_family_loads(self):
        path = write_yaml(VALID_FLAG)
        cfg = load_mapping(path)
        assert cfg["amount_format_family"] == "amount_plus_flag"
        assert cfg["locale"]["date_locale"] == "US"
        os.unlink(path)

    def test_column_map_preserved(self):
        path = write_yaml(VALID_SIGNED)
        cfg = load_mapping(path)
        assert cfg["column_map"]["Date"] == "transaction_date"
        assert cfg["column_map"]["Desc"] == "description"
        os.unlink(path)

    def test_drop_columns_preserved(self):
        path = write_yaml(VALID_SIGNED)
        cfg = load_mapping(path)
        assert "Balance" in cfg["drop_columns"]
        os.unlink(path)


class TestLoadMappingInvalid:
    def _write_and_remove_key(self, key: str) -> str:
        data = dict(VALID_SIGNED)
        del data[key]
        return write_yaml(data)

    def test_missing_bank_key_raises(self):
        path = self._write_and_remove_key("bank_key")
        with pytest.raises(ValueError, match="bank_key"):
            load_mapping(path)
        os.unlink(path)

    def test_missing_bank_name_raises(self):
        path = self._write_and_remove_key("bank_name")
        with pytest.raises(ValueError, match="bank_name"):
            load_mapping(path)
        os.unlink(path)

    def test_missing_amount_format_family_raises(self):
        path = self._write_and_remove_key("amount_format_family")
        with pytest.raises(ValueError, match="amount_format_family"):
            load_mapping(path)
        os.unlink(path)

    def test_unknown_family_raises(self):
        data = dict(VALID_SIGNED)
        data["amount_format_family"] = "totally_wrong"
        path = write_yaml(data)
        with pytest.raises(ValueError, match="Unknown amount_format_family"):
            load_mapping(path)
        os.unlink(path)

    def test_missing_date_key_raises(self):
        path = self._write_and_remove_key("date")
        with pytest.raises(ValueError, match="date"):
            load_mapping(path)
        os.unlink(path)

    def test_missing_signed_amount_key_raises(self):
        data = dict(VALID_SIGNED)
        data["amount"] = {}
        path = write_yaml(data)
        with pytest.raises(ValueError, match="amount.signed_amount"):
            load_mapping(path)
        os.unlink(path)

    def test_missing_dc_flag_values_raises(self):
        data = dict(VALID_FLAG)
        data["amount"] = {"amount_col": "TXN AMT", "dc_flag_col": "DR/CR", "dc_flag_values": {"debit": [], "credit": ["CR"]}}
        path = write_yaml(data)
        with pytest.raises(ValueError, match="dc_flag_values"):
            load_mapping(path)
        os.unlink(path)

    def test_overlapping_dc_flags_raises(self):
        data = dict(VALID_FLAG)
        data["amount"] = {"amount_col": "TXN AMT", "dc_flag_col": "DR/CR", "dc_flag_values": {"debit": ["DR"], "credit": ["DR"]}}
        path = write_yaml(data)
        with pytest.raises(ValueError, match="overlapping"):
            load_mapping(path)
        os.unlink(path)
