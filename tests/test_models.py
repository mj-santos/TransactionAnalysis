import pytest

from finance_etl.models import MappingConfig, parse_mapping_config


VALID = {
    "bank_key": "b",
    "bank_name": "B",
    "amount_format_family": "signed",
    "column_map": {"Date": "transaction_date", "Desc": "description"},
    "date": {"transaction_date": "Date"},
    "amount": {"signed_amount": "Amount"},
}


def test_parse_mapping_config_returns_typed_model():
    model = parse_mapping_config(VALID, "x.yaml")
    assert isinstance(model, MappingConfig)
    assert model.amount_format_family == "signed"


def test_parse_mapping_config_rejects_missing_key():
    bad = dict(VALID)
    del bad["bank_key"]
    with pytest.raises(ValueError, match="bank_key"):
        parse_mapping_config(bad, "x.yaml")
