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
