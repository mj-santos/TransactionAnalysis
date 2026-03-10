# ============================================================
# INCOME FILTER — canonical definition of "true income"
# Must be used in every SQL query that computes income totals.
#
# Rule: amount > 0 AND statement_type = 'bank'
#
# Why: CC positive amounts (payments, refunds) are not income.
# Only bank inflows represent actual earned/deposited income.
#
# DO NOT inline a different income condition anywhere in the
# codebase. If this rule needs to change, change it here only.
# See PROJECT.md BUG-6, BUG-7, BUG-8 for full history.
# ============================================================

INCOME_FILTER = "amount > 0 AND statement_type = 'bank'"


# ============================================================
# SHARED GROUP EVALUATION — used by merchant_rules + category_rules
# ============================================================

import re
from typing import Any


def _match_single(pattern: str, match_type: str, text: str,
                  compiled_regex: re.Pattern | None = None) -> bool:
    """Evaluate one condition against text."""
    if match_type == "contains":
        return pattern.lower() in text.lower()
    if match_type in ("startswith", "starts_with"):
        return text.lower().startswith(pattern.lower())
    if match_type == "exact":
        return text.lower() == pattern.lower()
    if match_type == "regex":
        return bool(compiled_regex and compiled_regex.search(text))
    return False


def evaluate_rule_groups(groups: list[dict], text: str,
                         compiled_regexes: dict[int, re.Pattern | None] | None = None) -> bool:
    """
    Evaluate grouped boolean conditions against a text string.
    All groups must pass (implicit AND between groups).
    Within each group, conditions combined by group_logic (AND|OR).

    Args:
        groups: list of group dicts with group_logic + conditions
        text: the string to match against (description or raw_category)
        compiled_regexes: optional dict mapping condition index to compiled regex
    Returns:
        True if all groups pass, False otherwise
    """
    if compiled_regexes is None:
        compiled_regexes = {}
    idx = 0
    for group in groups:
        group_logic = group.get("group_logic", "AND")
        conditions = group.get("conditions", [])
        group_results = []
        for cond in conditions:
            result = _match_single(
                cond.get("pattern", ""),
                cond.get("match_type", "contains"),
                text,
                compiled_regexes.get(idx),
            )
            if cond.get("negate"):
                result = not result
            group_results.append(result)
            idx += 1
        if not group_results:
            continue
        group_pass = all(group_results) if group_logic == "AND" else any(group_results)
        if not group_pass:
            return False
    return True
