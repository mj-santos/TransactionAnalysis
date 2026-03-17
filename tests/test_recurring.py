"""Tests for the recurring transaction detection engine."""
import datetime

import pytest

from finance_etl.recurring import (
    MIN_OCCURRENCES,
    RecurringPattern,
    _classify_frequency,
    _median,
    compute_monthly_recurring_total,
    detect_recurring,
    detect_annual_fee_suggestions,
    _suggestion_id,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestMedian:
    def test_odd_list(self):
        assert _median([3, 1, 2]) == 2

    def test_even_list(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_single(self):
        assert _median([7]) == 7

    def test_empty(self):
        assert _median([]) == 0.0


class TestClassifyFrequency:
    def test_weekly(self):
        assert _classify_frequency(7) == "weekly"

    def test_biweekly(self):
        assert _classify_frequency(14) == "biweekly"

    def test_monthly(self):
        assert _classify_frequency(30) == "monthly"

    def test_quarterly(self):
        assert _classify_frequency(91) == "quarterly"

    def test_annual(self):
        assert _classify_frequency(365) == "annual"

    def test_irregular(self):
        assert _classify_frequency(200) == "irregular"


# ---------------------------------------------------------------------------
# Monthly total computation
# ---------------------------------------------------------------------------

class TestComputeMonthlyTotal:
    def test_monthly_passthrough(self):
        patterns = [{"median_amount": 15.0, "frequency": "monthly"}]
        assert compute_monthly_recurring_total(patterns) == 15.0

    def test_annual_division(self):
        patterns = [{"median_amount": 120.0, "frequency": "annual"}]
        assert compute_monthly_recurring_total(patterns) == 10.0

    def test_weekly_multiplier(self):
        patterns = [{"median_amount": 10.0, "frequency": "weekly"}]
        expected = round(10.0 * 52 / 12, 2)
        assert compute_monthly_recurring_total(patterns) == expected

    def test_multiple_patterns(self):
        patterns = [
            {"median_amount": 15.0, "frequency": "monthly"},
            {"median_amount": 120.0, "frequency": "annual"},
        ]
        assert compute_monthly_recurring_total(patterns) == 25.0

    def test_yearly_alias(self):
        """'yearly' should be treated the same as 'annual' (÷12)."""
        patterns = [{"median_amount": 120.0, "frequency": "yearly"}]
        assert compute_monthly_recurring_total(patterns) == 10.0

    def test_empty(self):
        assert compute_monthly_recurring_total([]) == 0.0


# ---------------------------------------------------------------------------
# Detection engine (using a mock DuckDB connection)
# ---------------------------------------------------------------------------

class _FakeResult:
    """Mimics a DuckDB cursor result for testing."""
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Minimal mock of a DuckDB connection returning canned data."""
    def __init__(self, txn_rows, override_rows=None):
        self._txn_rows = txn_rows
        # Normalize override rows to 8-column tuples:
        # (merchant_key, is_recurring, label, amount, frequency, paused, last_date, next_estimated)
        normalized = []
        for row in (override_rows or []):
            if len(row) == 2:
                # Legacy 2-col: (merchant_key, is_recurring)
                normalized.append((row[0], row[1], row[0], None, None, False, None, None))
            elif len(row) == 5:
                # 5-col: (merchant_key, is_recurring, label, amount, frequency)
                normalized.append((*row, False, None, None))
            elif len(row) == 7:
                # 7-col: missing next_estimated
                normalized.append((*row, None))
            else:
                normalized.append(row)
        self._override_rows = normalized
        self._call_count = 0

    def execute(self, sql, params=None):
        self._call_count += 1
        if "recurring_overrides" in sql:
            return _FakeResult(self._override_rows)
        return _FakeResult(self._txn_rows)


def _make_monthly_txns(merchant, amount, start_date, count):
    """Generate `count` monthly transactions for testing."""
    rows = []
    d = datetime.date.fromisoformat(start_date)
    for _ in range(count):
        rows.append((merchant, d, abs(amount)))
        d += datetime.timedelta(days=30)
    return rows


class TestDetectRecurring:
    def test_detects_monthly_pattern(self):
        """A merchant with 5 monthly charges at the same amount is detected."""
        txns = _make_monthly_txns("Netflix", 15.99, "2024-01-15", 5)
        conn = _FakeConn(txns)
        results, _ = detect_recurring(conn)

        assert len(results) == 1
        r = results[0]
        assert r["merchant"] == "Netflix"
        assert r["median_amount"] == 15.99
        assert r["frequency"] == "monthly"
        assert r["occurrences"] == 5
        assert r["is_auto"] is True
        assert r["next_estimated"] is not None

    def test_ignores_few_occurrences(self):
        """Fewer than MIN_OCCURRENCES should not be flagged."""
        txns = _make_monthly_txns("OneOff", 50.0, "2024-01-01", MIN_OCCURRENCES - 1)
        conn = _FakeConn(txns)
        results, _ = detect_recurring(conn)
        assert len(results) == 0

    def test_ignores_irregular_intervals(self):
        """Random intervals should not pass the CV threshold."""
        txns = [
            ("Random Co", datetime.date(2024, 1, 1), 20.0),
            ("Random Co", datetime.date(2024, 1, 5), 20.0),
            ("Random Co", datetime.date(2024, 5, 20), 20.0),
            ("Random Co", datetime.date(2024, 5, 22), 20.0),
            ("Random Co", datetime.date(2024, 12, 1), 20.0),
        ]
        conn = _FakeConn(txns)
        results, _ = detect_recurring(conn)
        assert len(results) == 0

    def test_user_override_unmark(self):
        """A user override of is_recurring=False removes the auto-detected pattern."""
        txns = _make_monthly_txns("Spotify", 9.99, "2024-01-01", 6)
        overrides = [("Spotify", False)]
        conn = _FakeConn(txns, overrides)
        results, _ = detect_recurring(conn, include_overrides=True)
        assert len(results) == 0

    def test_user_override_mark(self):
        """A user can force-mark a merchant as recurring even with few data points."""
        txns = [
            ("NewSub", datetime.date(2024, 6, 1), 5.0),
            ("NewSub", datetime.date(2024, 7, 1), 5.0),
        ]
        overrides = [("NewSub", True)]
        conn = _FakeConn(txns, overrides)
        results, _ = detect_recurring(conn, include_overrides=True)
        assert len(results) == 1
        assert results[0]["merchant"] == "NewSub"
        assert results[0]["is_auto"] is False

    def test_varying_amounts_rejected(self):
        """Amounts that vary too much should not be flagged."""
        txns = [
            ("Grocery", datetime.date(2024, 1, 1), 50.0),
            ("Grocery", datetime.date(2024, 2, 1), 120.0),
            ("Grocery", datetime.date(2024, 3, 1), 30.0),
            ("Grocery", datetime.date(2024, 4, 1), 200.0),
        ]
        conn = _FakeConn(txns)
        results, _ = detect_recurring(conn)
        assert len(results) == 0

    def test_multiple_merchants(self):
        """Multiple merchants with valid patterns should all be returned."""
        txns = (
            _make_monthly_txns("Netflix", 15.99, "2024-01-01", 4) +
            _make_monthly_txns("Spotify", 9.99, "2024-01-05", 4) +
            [("OneOff", datetime.date(2024, 3, 1), 100.0)]  # too few
        )
        conn = _FakeConn(txns)
        results, _ = detect_recurring(conn)
        merchants = {r["merchant"] for r in results}
        assert "Netflix" in merchants
        assert "Spotify" in merchants
        assert "OneOff" not in merchants


# ---------------------------------------------------------------------------
# Annual fee / membership keyword detection
# ---------------------------------------------------------------------------

class _FakeAnnualConn:
    """Mock connection for detect_annual_fee_suggestions."""
    def __init__(self, txn_rows):
        self._txn_rows = txn_rows

    def execute(self, sql, params=None):
        return _FakeResult(self._txn_rows)


class TestAnnualFeeSuggestions:
    def test_card_annual_fee_detected(self):
        """RENEWAL MEMBERSHIP FEE on 'Gold Card' produces a suggestion."""
        rows = [
            ("fp1", "RENEWAL MEMBERSHIP FEE", 250.0,
             datetime.date(2024, 6, 15), "American Express", "Gold Card", None),
        ]
        conn = _FakeAnnualConn(rows)
        results = detect_annual_fee_suggestions(conn)
        assert len(results) == 1
        s = results[0]
        assert s["label"] == "Gold Card Annual Fee"
        assert s["amount"] == 250.0
        assert s["frequency"] == "annual"
        assert s["is_card_fee"] is True
        assert s["account_name"] == "Gold Card"
        assert s["next_estimated"] == "2025-06-15"

    def test_amazon_prime_detected(self):
        """AMAZON PRIME MEMBERSHIP charge produces an Amazon Prime suggestion."""
        rows = [
            ("fp2", "AMAZON PRIME MEMBERSHIP", 139.0,
             datetime.date(2024, 3, 1), "Chase", "Sapphire", "Amazon"),
        ]
        conn = _FakeAnnualConn(rows)
        results = detect_annual_fee_suggestions(conn)
        assert len(results) == 1
        assert results[0]["label"] == "Amazon Prime"
        assert results[0]["is_card_fee"] is False

    def test_dismissed_suggestion_excluded(self):
        """Dismissed suggestion should not appear."""
        rows = [
            ("fp1", "RENEWAL MEMBERSHIP FEE", 250.0,
             datetime.date(2024, 6, 15), "Amex", "Gold", None),
        ]
        conn = _FakeAnnualConn(rows)
        sid = _suggestion_id("renewal membership fee", "Gold")
        results = detect_annual_fee_suggestions(conn, dismissed_ids={sid})
        assert len(results) == 0

    def test_existing_override_excluded(self):
        """Suggestion whose label matches an existing override is excluded."""
        rows = [
            ("fp1", "RENEWAL MEMBERSHIP FEE", 250.0,
             datetime.date(2024, 6, 15), "Amex", "Gold", None),
        ]
        conn = _FakeAnnualConn(rows)
        results = detect_annual_fee_suggestions(
            conn, existing_override_keys={"Gold Annual Fee"}
        )
        assert len(results) == 0

    def test_different_accounts_separate_suggestions(self):
        """Same keyword on different accounts produces separate suggestions."""
        rows = [
            ("fp1", "ANNUAL FEE", 250.0,
             datetime.date(2024, 6, 1), "Amex", "Gold Card", None),
            ("fp2", "ANNUAL FEE", 95.0,
             datetime.date(2024, 7, 1), "Chase", "Sapphire Preferred", None),
        ]
        conn = _FakeAnnualConn(rows)
        results = detect_annual_fee_suggestions(conn)
        assert len(results) == 2
        labels = {s["label"] for s in results}
        assert "Gold Card Annual Fee" in labels
        assert "Sapphire Preferred Annual Fee" in labels

    def test_no_match_returns_empty(self):
        """Transactions with no matching keywords produce no suggestions."""
        rows = [
            ("fp1", "STARBUCKS COFFEE #1234", 5.50,
             datetime.date(2024, 1, 1), "Chase", "Checking", "Starbucks"),
        ]
        conn = _FakeAnnualConn(rows)
        results = detect_annual_fee_suggestions(conn)
        assert len(results) == 0



# ---------------------------------------------------------------------------
# Bug fix: override with no matching transactions (BUG-30/31)
# ---------------------------------------------------------------------------

class TestOverrideWithNoTransactions:
    """BUG-30: Accepted annual fee suggestions should appear in recurring list
    even when merchant_key (the label) has no matching transactions."""

    def test_override_with_no_matching_transactions_appears(self):
        """An override whose merchant_key matches no transaction merchant
        should still show in results using stored amount/frequency."""
        txns = _make_monthly_txns("Netflix", 15.99, "2024-01-01", 5)
        # Override for "Amazon Prime Annual" — no transactions with that merchant
        overrides = [("Amazon Prime Annual", True, "Amazon Prime Annual", 139.0, "annual")]
        conn = _FakeConn(txns, overrides)
        results, _ = detect_recurring(conn, include_overrides=True)

        merchants = {r["merchant"] for r in results}
        assert "Amazon Prime Annual" in merchants, (
            "Override with no matching transactions should still appear"
        )
        prime = [r for r in results if r["merchant"] == "Amazon Prime Annual"][0]
        assert prime["median_amount"] == 139.0
        assert prime["frequency"] == "annual"
        assert prime["is_auto"] is False
        assert prime["occurrences"] == 0

    def test_override_with_matching_transactions_uses_tx_data(self):
        """When the override merchant_key matches real transactions, use tx data."""
        txns = _make_monthly_txns("Spotify", 9.99, "2024-01-01", 5)
        overrides = [("Spotify", True, "Spotify", 9.99, "monthly")]
        conn = _FakeConn(txns, overrides)
        results, _ = detect_recurring(conn, include_overrides=True)

        # Spotify already auto-detected — override should not create duplicate
        spotify_results = [r for r in results if r["merchant"] == "Spotify"]
        assert len(spotify_results) == 1
        assert spotify_results[0]["occurrences"] == 5  # from real transactions


class TestMicrosoft365Detection:
    def test_microsoft_365_detected(self):
        """Microsoft 365 keyword match."""
        rows = [
            ("fp1", "MICROSOFT 365 PERSONAL", 99.99,
             datetime.date(2024, 9, 1), "BofA", "Checking", "Microsoft"),
        ]
        conn = _FakeAnnualConn(rows)
        results = detect_annual_fee_suggestions(conn)
        assert len(results) == 1
        assert results[0]["label"] == "Microsoft 365"


# ---------------------------------------------------------------------------
# Pause / Resume overrides
# ---------------------------------------------------------------------------

class TestPausedOverrides:
    """Paused recurring charges should appear in the paused list, not active."""

    def test_paused_override_excluded_from_active(self):
        """A paused override appears in paused list, not active."""
        txns = _make_monthly_txns("Netflix", 15.99, "2024-01-15", 5)
        # 7-col: (merchant_key, is_recurring, label, amount, frequency, paused, last_date)
        overrides = [("Netflix", True, "Netflix", 15.99, "monthly", True, None)]
        conn = _FakeConn(txns, overrides)
        active, paused = detect_recurring(conn, include_overrides=True)

        active_merchants = {r["merchant"] for r in active}
        paused_merchants = {r["merchant"] for r in paused}
        assert "Netflix" not in active_merchants, "Paused merchant should not be in active"
        assert "Netflix" in paused_merchants, "Paused merchant should be in paused list"
        assert paused[0]["paused"] is True

    def test_resumed_override_in_active(self):
        """An override with paused=False appears in active list."""
        txns = _make_monthly_txns("Spotify", 9.99, "2024-01-01", 5)
        overrides = [("Spotify", True, "Spotify", 9.99, "monthly", False, None)]
        conn = _FakeConn(txns, overrides)
        active, paused = detect_recurring(conn, include_overrides=True)

        active_merchants = {r["merchant"] for r in active}
        assert "Spotify" in active_merchants
        assert len(paused) == 0

    def test_auto_detected_with_pause_override(self):
        """Auto-detected pattern paused via override moves to paused list."""
        txns = _make_monthly_txns("Hulu", 14.99, "2024-01-01", 5)
        overrides = [("Hulu", True, None, None, None, True, None)]
        conn = _FakeConn(txns, overrides)
        active, paused = detect_recurring(conn, include_overrides=True)

        active_merchants = {r["merchant"] for r in active}
        paused_merchants = {r["merchant"] for r in paused}
        assert "Hulu" not in active_merchants
        assert "Hulu" in paused_merchants


# ---------------------------------------------------------------------------
# last_date for synthetic patterns
# ---------------------------------------------------------------------------

class TestOverrideLastDate:
    """Stored last_date should be used for next_estimated computation."""

    def test_override_with_last_date_computes_next_estimated(self):
        """Stored last_date produces valid next_estimated."""
        # Override with no matching transactions but has last_date
        overrides = [("Amazon Prime", True, "Amazon Prime", 139.0, "annual",
                       False, "2024-06-15")]
        conn = _FakeConn([], overrides)
        active, _ = detect_recurring(conn, include_overrides=True)

        assert len(active) == 1
        prime = active[0]
        assert prime["merchant"] == "Amazon Prime"
        assert prime["last_date"] == "2024-06-15"
        assert prime["next_estimated"] == "2025-06-15"  # +365 days
        assert prime["median_amount"] == 139.0

    def test_override_without_last_date_backward_compat(self):
        """Override with no last_date still works (empty/None output)."""
        overrides = [("Old Sub", True, "Old Sub", 50.0, "monthly", False, None)]
        conn = _FakeConn([], overrides)
        active, _ = detect_recurring(conn, include_overrides=True)

        assert len(active) == 1
        assert active[0]["last_date"] == ""
        assert active[0]["next_estimated"] is None
