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
        self._override_rows = override_rows or []
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
        results = detect_recurring(conn)

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
        results = detect_recurring(conn)
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
        results = detect_recurring(conn)
        assert len(results) == 0

    def test_user_override_unmark(self):
        """A user override of is_recurring=False removes the auto-detected pattern."""
        txns = _make_monthly_txns("Spotify", 9.99, "2024-01-01", 6)
        overrides = [("Spotify", False)]
        conn = _FakeConn(txns, overrides)
        results = detect_recurring(conn, include_overrides=True)
        assert len(results) == 0

    def test_user_override_mark(self):
        """A user can force-mark a merchant as recurring even with few data points."""
        txns = [
            ("NewSub", datetime.date(2024, 6, 1), 5.0),
            ("NewSub", datetime.date(2024, 7, 1), 5.0),
        ]
        overrides = [("NewSub", True)]
        conn = _FakeConn(txns, overrides)
        results = detect_recurring(conn, include_overrides=True)
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
        results = detect_recurring(conn)
        assert len(results) == 0

    def test_multiple_merchants(self):
        """Multiple merchants with valid patterns should all be returned."""
        txns = (
            _make_monthly_txns("Netflix", 15.99, "2024-01-01", 4) +
            _make_monthly_txns("Spotify", 9.99, "2024-01-05", 4) +
            [("OneOff", datetime.date(2024, 3, 1), 100.0)]  # too few
        )
        conn = _FakeConn(txns)
        results = detect_recurring(conn)
        merchants = {r["merchant"] for r in results}
        assert "Netflix" in merchants
        assert "Spotify" in merchants
        assert "OneOff" not in merchants
