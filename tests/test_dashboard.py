"""Tests for dashboard-related endpoints including version and tab routing."""

import calendar
import re
from datetime import date
from pathlib import Path

from finance_etl.db import get_connection


# ---------------------------------------------------------------------------
# resolveTransactionTab logic (mirrors the JS function in app.js)
# ---------------------------------------------------------------------------

def _resolve_transaction_tab(transactions):
    """Python equivalent of resolveTransactionTab() in app.js."""
    cc = sum(1 for t in transactions if t.get("statement_type") == "credit_card")
    bank = sum(1 for t in transactions if t.get("statement_type") == "bank")
    if cc > 0 and bank == 0:
        return "credit_card"
    if bank > 0 and cc == 0:
        return "bank"
    return "credit_card" if cc >= bank else "bank"


def _init_db(tmp_path):
    """Create and return an initialized db_path (runs migrations via get_connection)."""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(db_path)
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Version string tests (read directly from pyproject.toml)
# ---------------------------------------------------------------------------

def _read_pyproject_version():
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    for line in pyproject.read_text().splitlines():
        if line.startswith("version"):
            return line.split("=")[1].strip().strip('"')
    return None


def test_version_is_valid_semver():
    """pyproject.toml version must be a valid semver string."""
    v = _read_pyproject_version()
    assert v is not None
    assert re.match(r"^\d+\.\d+\.\d+$", v), f"Version '{v}' is not valid semver"


def test_version_is_non_empty():
    assert _read_pyproject_version() not in (None, "")


# ---------------------------------------------------------------------------
# resolveTransactionTab tests — mirrors JS logic for tab routing
# ---------------------------------------------------------------------------

def test_resolve_tab_cc_only():
    """All transactions are credit_card → route to credit_card."""
    txns = [{"statement_type": "credit_card"} for _ in range(5)]
    assert _resolve_transaction_tab(txns) == "credit_card"


def test_resolve_tab_bank_only():
    """All transactions are bank → route to bank."""
    txns = [{"statement_type": "bank"} for _ in range(5)]
    assert _resolve_transaction_tab(txns) == "bank"


def test_resolve_tab_mixed_majority_cc():
    """7 CC + 3 bank → route to credit_card (majority)."""
    txns = ([{"statement_type": "credit_card"}] * 7 +
            [{"statement_type": "bank"}] * 3)
    assert _resolve_transaction_tab(txns) == "credit_card"


def test_resolve_tab_mixed_majority_bank():
    """3 CC + 7 bank → route to bank (majority)."""
    txns = ([{"statement_type": "credit_card"}] * 3 +
            [{"statement_type": "bank"}] * 7)
    assert _resolve_transaction_tab(txns) == "bank"


def test_resolve_tab_tie_defaults_credit_card():
    """5 CC + 5 bank → tie defaults to credit_card."""
    txns = ([{"statement_type": "credit_card"}] * 5 +
            [{"statement_type": "bank"}] * 5)
    assert _resolve_transaction_tab(txns) == "credit_card"


# ---------------------------------------------------------------------------
# Helpers for dashboard summary tests
# ---------------------------------------------------------------------------

def _seed_spending(db_path, rows):
    """Insert spending transactions into transactions_norm.

    Each row: (fingerprint, date_str, category_parent, category_normalized, amount)
    """
    conn = get_connection(db_path)
    for fp, txn_date, cat_parent, cat_norm, amount in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_fingerprint, transaction_date, description, amount, merchant, "
            " category, category_normalized, category_parent, "
            " statement_type, transaction_subtype, resolved_amount, "
            " run_id, bank_name, account_name, account_id, source_file, source_row, file_hash) "
            "VALUES (?, ?, 'desc', ?, 'Merchant', ?, ?, ?, "
            "'credit_card', 'spending', ?, "
            "'run1', 'Bank', 'Acct', 'a1', 'f.csv', 1, 'h1')",
            [fp, txn_date, amount, cat_norm, cat_norm, cat_parent, amount],
        )
    conn.close()


# ---------------------------------------------------------------------------
# Dashboard SQL logic helpers — mirror the endpoint queries directly
# ---------------------------------------------------------------------------

def _dash_mtd(conn, year, month):
    row = conn.execute(
        "SELECT COALESCE(SUM(resolved_amount),0), COUNT(*) FROM transactions_norm "
        "WHERE transaction_subtype='spending' AND YEAR(transaction_date)=? AND MONTH(transaction_date)=?",
        [year, month],
    ).fetchone()
    return float(row[0]), int(row[1])


def _dash_prev(conn, year, month):
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    row = conn.execute(
        "SELECT COALESCE(SUM(resolved_amount),0) FROM transactions_norm "
        "WHERE transaction_subtype='spending' AND YEAR(transaction_date)=? AND MONTH(transaction_date)=?",
        [prev_year, prev_month],
    ).fetchone()
    return float(row[0])


def _dash_top_cats(conn, year, month):
    rows = conn.execute(
        "SELECT COALESCE(category_normalized, category_parent, category) AS grp, "
        "SUM(resolved_amount) AS total FROM transactions_norm "
        "WHERE transaction_subtype='spending' AND YEAR(transaction_date)=? AND MONTH(transaction_date)=? "
        "AND COALESCE(category_normalized, category_parent, category) IS NOT NULL "
        "GROUP BY grp ORDER BY total DESC LIMIT 8",
        [year, month],
    ).fetchall()
    return [{"category_parent": r[0], "total_amount": float(r[1])} for r in rows]


def _dash_prev_cats(conn, year, month):
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    rows = conn.execute(
        "SELECT COALESCE(category_normalized, category_parent, category) AS grp, "
        "SUM(resolved_amount) AS total FROM transactions_norm "
        "WHERE transaction_subtype='spending' AND YEAR(transaction_date)=? AND MONTH(transaction_date)=? "
        "AND COALESCE(category_normalized, category_parent, category) IS NOT NULL GROUP BY grp",
        [prev_year, prev_month],
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def _compute_forecast(mtd_spend, year, month):
    today = date.today()
    days_in_month = calendar.monthrange(year, month)[1]
    days_elapsed = today.day if (year == today.year and month == today.month) else days_in_month
    forecast = round(mtd_spend / days_elapsed * days_in_month, 2) if days_elapsed > 0 else 0.0
    return forecast, days_elapsed, days_in_month


def _compute_category_changes(top_cats, prev_cat_map):
    changes = []
    for c in top_cats:
        cat = c["category_parent"]
        cur = c["total_amount"]
        prev = prev_cat_map.get(cat, 0.0)
        if prev > 0:
            delta_pct = round((cur - prev) / prev * 100, 1)
        elif cur > 0:
            delta_pct = 100.0
        else:
            delta_pct = 0.0
        changes.append({"category": cat, "current": cur, "previous": prev, "delta_pct": delta_pct})
    changes.sort(key=lambda x: abs(x["delta_pct"]), reverse=True)
    return changes


# ---------------------------------------------------------------------------
# mtd_spend tests
# ---------------------------------------------------------------------------

def test_dashboard_empty_db_zero_spend(tmp_path: Path):
    """Empty DB → mtd_spend=0, mtd_count=0."""
    db_path = _init_db(tmp_path)
    conn = get_connection(db_path, read_only=True)
    today = date.today()
    spend, count = _dash_mtd(conn, today.year, today.month)
    conn.close()
    assert spend == 0.0
    assert count == 0


def test_dashboard_mtd_spend_sums_spending_only(tmp_path: Path):
    """Only 'spending' subtype rows are counted; income rows are excluded."""
    db_path = _init_db(tmp_path)
    today = date.today()
    yr, mo = today.year, today.month
    month_str = f"{yr}-{mo:02d}"
    _seed_spending(db_path, [
        ("fp1", f"{month_str}-01", "Food", "Restaurants", 50.00),
        ("fp2", f"{month_str}-05", "Food", "Groceries", 120.00),
    ])
    # income row — must NOT appear in mtd_spend
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_fingerprint, transaction_date, description, amount, merchant, "
        " category, category_normalized, category_parent, "
        " statement_type, transaction_subtype, resolved_amount, "
        " run_id, bank_name, account_name, account_id, source_file, source_row, file_hash) "
        "VALUES ('fp3', ?, 'Paycheck', 2000, 'Employer', NULL, NULL, NULL, "
        "'bank', 'income', 2000.00, 'run1', 'Bank', 'Acct', 'a1', 'f.csv', 2, 'h2')",
        [f"{month_str}-10"],
    )
    conn.close()

    conn = get_connection(db_path, read_only=True)
    spend, count = _dash_mtd(conn, yr, mo)
    conn.close()
    assert spend == 170.00
    assert count == 2


def test_dashboard_prev_spend_correct(tmp_path: Path):
    """prev_spend reads from the calendar month before the requested month."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [
        ("fp-prev", "2025-11-15", "Food", "Restaurants", 200.00),
        ("fp-curr", "2025-12-10", "Food", "Restaurants", 300.00),
    ])
    conn = get_connection(db_path, read_only=True)
    prev = _dash_prev(conn, 2025, 12)
    conn.close()
    assert prev == 200.00


def test_dashboard_pct_change_calculation(tmp_path: Path):
    """pct_change = (current - prev) / prev * 100."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [
        ("fp-prev", "2025-11-15", "Food", "Restaurants", 200.00),
        ("fp-curr", "2025-12-10", "Food", "Restaurants", 300.00),
    ])
    conn = get_connection(db_path, read_only=True)
    spend, _ = _dash_mtd(conn, 2025, 12)
    prev = _dash_prev(conn, 2025, 12)
    conn.close()
    pct = round((spend - prev) / prev * 100, 1) if prev > 0 else None
    assert pct == 50.0


def test_dashboard_pct_change_none_when_no_prior(tmp_path: Path):
    """pct_change is None when prev_spend is 0."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [("fp1", "2025-01-05", "Food", "Restaurants", 100.00)])
    conn = get_connection(db_path, read_only=True)
    prev = _dash_prev(conn, 2025, 1)
    conn.close()
    assert prev == 0.0  # no December 2024 data → pct_change would be None


def test_dashboard_prev_month_wraps_to_december(tmp_path: Path):
    """January's prior month is December of the previous year."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [("fp-dec", "2024-12-20", "Food", "Groceries", 150.00)])
    conn = get_connection(db_path, read_only=True)
    prev = _dash_prev(conn, 2025, 1)
    conn.close()
    assert prev == 150.00


# ---------------------------------------------------------------------------
# Forecast tests
# ---------------------------------------------------------------------------

def test_forecast_past_month_equals_actual(tmp_path: Path):
    """For a fully-elapsed past month, forecast == mtd_spend."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [("fp1", "2025-03-15", "Food", "Restaurants", 310.00)])
    conn = get_connection(db_path, read_only=True)
    spend, _ = _dash_mtd(conn, 2025, 3)
    conn.close()
    forecast, days_elapsed, days_in_month = _compute_forecast(spend, 2025, 3)
    assert days_in_month == 31
    assert days_elapsed == 31
    assert forecast == 310.00


def test_forecast_june_has_30_days(tmp_path: Path):
    """days_in_month is correct for a 30-day month."""
    _, days_elapsed, days_in_month = _compute_forecast(0.0, 2025, 6)
    assert days_in_month == 30


def test_forecast_february_non_leap(tmp_path: Path):
    """February 2025 (non-leap) has 28 days."""
    _, _, days_in_month = _compute_forecast(0.0, 2025, 2)
    assert days_in_month == 28


def test_forecast_february_leap(tmp_path: Path):
    """February 2024 (leap year) has 29 days."""
    _, _, days_in_month = _compute_forecast(0.0, 2024, 2)
    assert days_in_month == 29


def test_forecast_linear_projection(tmp_path: Path):
    """Current-month forecast = spend / days_elapsed * days_in_month."""
    today = date.today()
    yr, mo = today.year, today.month
    days_elapsed = today.day
    days_in_month = calendar.monthrange(yr, mo)[1]
    spend = 10.0 * days_elapsed  # $10/day
    forecast, _, _ = _compute_forecast(spend, yr, mo)
    assert forecast == round(10.0 * days_in_month, 2)


# ---------------------------------------------------------------------------
# Category changes tests
# ---------------------------------------------------------------------------

def test_category_changes_structure(tmp_path: Path):
    """Each change entry has category, current, previous, delta_pct."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [
        ("fp1", "2025-12-10", "Food", "Restaurants", 100.00),
        ("fp2", "2025-11-10", "Food", "Restaurants", 80.00),
    ])
    conn = get_connection(db_path, read_only=True)
    top = _dash_top_cats(conn, 2025, 12)
    prev_map = _dash_prev_cats(conn, 2025, 12)
    conn.close()
    changes = _compute_category_changes(top, prev_map)
    assert len(changes) >= 1
    for key in ("category", "current", "previous", "delta_pct"):
        assert key in changes[0]


def test_category_changes_delta_calculation(tmp_path: Path):
    """delta_pct = (current - previous) / previous * 100."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [
        ("fp-c", "2025-06-15", "Travel", "Flights", 300.00),
        ("fp-p", "2025-05-15", "Travel", "Flights", 200.00),
    ])
    conn = get_connection(db_path, read_only=True)
    top = _dash_top_cats(conn, 2025, 6)
    prev_map = _dash_prev_cats(conn, 2025, 6)
    conn.close()
    changes = _compute_category_changes(top, prev_map)
    entry = next(c for c in changes if c["category"] == "Flights")
    assert entry["current"] == 300.00
    assert entry["previous"] == 200.00
    assert entry["delta_pct"] == 50.0


def test_category_changes_new_category_100_pct(tmp_path: Path):
    """Category with no prior month data → delta_pct=100, previous=0."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [("fp1", "2025-08-10", "Entertainment", "Streaming", 50.00)])
    conn = get_connection(db_path, read_only=True)
    top = _dash_top_cats(conn, 2025, 8)
    prev_map = _dash_prev_cats(conn, 2025, 8)
    conn.close()
    changes = _compute_category_changes(top, prev_map)
    entry = next(c for c in changes if c["category"] == "Streaming")
    assert entry["delta_pct"] == 100.0
    assert entry["previous"] == 0.0


def test_category_changes_sorted_by_abs_delta(tmp_path: Path):
    """category_changes sorted descending by |delta_pct|."""
    db_path = _init_db(tmp_path)
    # Dining: +50%, Travel: +200% → Travel first
    _seed_spending(db_path, [
        ("fp-d-c", "2025-09-10", "Food", "Dining", 150.00),
        ("fp-d-p", "2025-08-10", "Food", "Dining", 100.00),
        ("fp-t-c", "2025-09-15", "Travel", "Hotels", 300.00),
        ("fp-t-p", "2025-08-15", "Travel", "Hotels", 100.00),
    ])
    conn = get_connection(db_path, read_only=True)
    top = _dash_top_cats(conn, 2025, 9)
    prev_map = _dash_prev_cats(conn, 2025, 9)
    conn.close()
    changes = _compute_category_changes(top, prev_map)
    assert len(changes) >= 2
    assert abs(changes[0]["delta_pct"]) >= abs(changes[1]["delta_pct"])


def test_category_changes_decrease_negative_delta(tmp_path: Path):
    """Spending decrease → negative delta_pct."""
    db_path = _init_db(tmp_path)
    _seed_spending(db_path, [
        ("fp-c", "2025-04-10", "Food", "Dining", 100.00),
        ("fp-p", "2025-03-10", "Food", "Dining", 200.00),
    ])
    conn = get_connection(db_path, read_only=True)
    top = _dash_top_cats(conn, 2025, 4)
    prev_map = _dash_prev_cats(conn, 2025, 4)
    conn.close()
    changes = _compute_category_changes(top, prev_map)
    entry = next(c for c in changes if c["category"] == "Dining")
    assert entry["delta_pct"] == -50.0
