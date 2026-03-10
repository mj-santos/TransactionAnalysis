"""Tests for merchant rule grouped boolean logic."""
from finance_etl.merchant_rules import CompiledRule


def test_or_group_matches_any_condition():
    """An OR group matches if any condition in the group matches."""
    rule = CompiledRule(
        id=1, pattern="AMAZON", match_type="contains", merchant="Amazon", priority=0,
        conditions={"groups": [
            {"group_logic": "OR", "conditions": [
                {"match_type": "contains", "pattern": "AMAZON", "negate": False},
                {"match_type": "contains", "pattern": "AMZN", "negate": False},
            ]},
        ]},
    )
    assert rule.matches("AMAZON ORDER 123")
    assert rule.matches("AMZN PURCHASE")
    assert not rule.matches("WALMART GROCERY")


def test_and_group_requires_all_conditions():
    """An AND group matches only if all conditions in the group match."""
    rule = CompiledRule(
        id=2, pattern="COFFEE", match_type="contains", merchant="Coffee Shop", priority=0,
        conditions={"groups": [
            {"group_logic": "AND", "conditions": [
                {"match_type": "contains", "pattern": "COFFEE", "negate": False},
                {"match_type": "contains", "pattern": "SHOP", "negate": False},
            ]},
        ]},
    )
    assert rule.matches("COFFEE SHOP DOWNTOWN")
    assert not rule.matches("COFFEE HOUSE")
    assert not rule.matches("DONUT SHOP")


def test_multi_group_all_must_pass():
    """All groups must pass (implicit AND between groups)."""
    rule = CompiledRule(
        id=3, pattern="AMAZON", match_type="contains", merchant="Amazon", priority=0,
        conditions={"groups": [
            {"group_logic": "OR", "conditions": [
                {"match_type": "contains", "pattern": "AMAZON", "negate": False},
                {"match_type": "contains", "pattern": "AMZN", "negate": False},
            ]},
            {"group_logic": "AND", "conditions": [
                {"match_type": "contains", "pattern": "FRESH", "negate": False},
            ]},
        ]},
    )
    # Must match group 1 (AMAZON or AMZN) AND group 2 (FRESH)
    assert rule.matches("AMAZON FRESH DELIVERY")
    assert rule.matches("AMZN FRESH ORDER")
    assert not rule.matches("AMAZON ORDER")  # Fails group 2
    assert not rule.matches("WHOLE FOODS FRESH")  # Fails group 1


def test_negate_condition_in_group():
    """A negated condition inverts the match result."""
    rule = CompiledRule(
        id=4, pattern="UBER", match_type="contains", merchant="Uber", priority=0,
        conditions={"groups": [
            {"group_logic": "AND", "conditions": [
                {"match_type": "contains", "pattern": "UBER", "negate": False},
                {"match_type": "contains", "pattern": "EATS", "negate": True},
            ]},
        ]},
    )
    assert rule.matches("UBER TRIP")
    assert not rule.matches("UBER EATS ORDER")
    assert not rule.matches("LYFT RIDE")


def test_legacy_flat_rule_still_works():
    """Legacy flat conditions (list, not grouped dict) still match correctly."""
    rule = CompiledRule(
        id=5, pattern="STARBUCKS", match_type="contains", merchant="Starbucks", priority=0,
        conditions=[
            {"match_type": "contains", "pattern": "STARBUCKS", "negate": False},
            {"match_type": "contains", "pattern": "RESERVE", "negate": True},
        ],
        logic="AND",
    )
    assert rule.matches("STARBUCKS COFFEE")
    assert not rule.matches("STARBUCKS RESERVE ROASTERY")
    assert not rule.matches("DUNKIN DONUTS")


def test_example_amazon_not_prime():
    """
    Example from spec: group1 OR [AMAZON, AMZN] + group2 AND NOT [PRIME]
    Matches Amazon orders but excludes Prime membership charges.
    """
    rule = CompiledRule(
        id=6, pattern="AMAZON", match_type="contains", merchant="Amazon", priority=0,
        conditions={"groups": [
            {"group_logic": "OR", "conditions": [
                {"match_type": "contains", "pattern": "AMAZON", "negate": False},
                {"match_type": "contains", "pattern": "AMZN", "negate": False},
            ]},
            {"group_logic": "AND", "conditions": [
                {"match_type": "contains", "pattern": "PRIME", "negate": True},
            ]},
        ]},
    )
    assert rule.matches("AMAZON ORDER")
    assert not rule.matches("AMAZON PRIME")
    assert rule.matches("AMZN PURCHASE")
    assert not rule.matches("AMZN PRIME MEMBERSHIP")
