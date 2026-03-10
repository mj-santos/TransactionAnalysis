"""Tests for shared group evaluation utility in query_helpers."""
from finance_etl.utils.query_helpers import evaluate_rule_groups


def test_single_group_or_logic():
    groups = [{"group_logic": "OR", "conditions": [
        {"match_type": "contains", "pattern": "AMAZON"},
        {"match_type": "contains", "pattern": "AMZN"},
    ]}]
    assert evaluate_rule_groups(groups, "AMAZON ORDER")
    assert evaluate_rule_groups(groups, "AMZN PURCHASE")
    assert not evaluate_rule_groups(groups, "WALMART")


def test_single_group_and_logic():
    groups = [{"group_logic": "AND", "conditions": [
        {"match_type": "contains", "pattern": "COFFEE"},
        {"match_type": "contains", "pattern": "SHOP"},
    ]}]
    assert evaluate_rule_groups(groups, "COFFEE SHOP")
    assert not evaluate_rule_groups(groups, "COFFEE HOUSE")
    assert not evaluate_rule_groups(groups, "DONUT SHOP")


def test_multi_group_all_must_pass():
    groups = [
        {"group_logic": "OR", "conditions": [
            {"match_type": "contains", "pattern": "AMAZON"},
            {"match_type": "contains", "pattern": "AMZN"},
        ]},
        {"group_logic": "AND", "conditions": [
            {"match_type": "contains", "pattern": "FRESH"},
        ]},
    ]
    assert evaluate_rule_groups(groups, "AMAZON FRESH")
    assert not evaluate_rule_groups(groups, "AMAZON ORDER")
    assert not evaluate_rule_groups(groups, "WHOLE FOODS FRESH")


def test_negate_in_group():
    groups = [{"group_logic": "AND", "conditions": [
        {"match_type": "contains", "pattern": "UBER"},
        {"match_type": "contains", "pattern": "EATS", "negate": True},
    ]}]
    assert evaluate_rule_groups(groups, "UBER TRIP")
    assert not evaluate_rule_groups(groups, "UBER EATS")
    assert not evaluate_rule_groups(groups, "LYFT RIDE")


def test_exact_match_type():
    groups = [{"group_logic": "AND", "conditions": [
        {"match_type": "exact", "pattern": "Restaurant-Restaurant"},
    ]}]
    assert evaluate_rule_groups(groups, "Restaurant-Restaurant")
    assert evaluate_rule_groups(groups, "restaurant-restaurant")
    assert not evaluate_rule_groups(groups, "Restaurant-Bar")


def test_contains_match_type():
    groups = [{"group_logic": "AND", "conditions": [
        {"match_type": "contains", "pattern": "Merchandise"},
    ]}]
    assert evaluate_rule_groups(groups, "Merchandise & Supplies-Groceries")
    assert not evaluate_rule_groups(groups, "Travel-Airline")


def test_starts_with_match_type():
    groups = [{"group_logic": "AND", "conditions": [
        {"match_type": "starts_with", "pattern": "Merchandise"},
    ]}]
    assert evaluate_rule_groups(groups, "Merchandise & Supplies-Groceries")
    assert not evaluate_rule_groups(groups, "General Merchandise")
