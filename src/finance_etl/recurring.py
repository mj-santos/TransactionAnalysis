"""Recurring transaction detection engine.

Analyzes transaction history to identify recurring charges by grouping on
normalized merchant name and looking for regular intervals (weekly, monthly,
annual) with consistent amounts.  A pattern is flagged as recurring only when
it has appeared 3+ times.

User overrides (manual mark/unmark) are stored in the ``recurring_overrides``
DB table and take precedence over auto-detection.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

# Frequency labels and their approximate day ranges used for classification
_FREQ_RANGES: list[tuple[str, int, int]] = [
    ("weekly",   4,   10),
    ("biweekly", 11,  18),
    ("monthly",  25,  38),
    ("quarterly", 80, 110),
    ("annual",   340, 400),
]

# Minimum occurrences before auto-flagging as recurring
MIN_OCCURRENCES = 3

# Maximum coefficient of variation (stddev/mean) for the interval to be
# considered "regular".  0.35 allows ~35 % jitter (e.g. 28-34 day cycles).
MAX_INTERVAL_CV = 0.35

# Maximum coefficient of variation for amounts
MAX_AMOUNT_CV = 0.30


@dataclass
class RecurringPattern:
    """A detected (or user-overridden) recurring charge."""
    merchant: str
    median_amount: float
    frequency: str            # weekly | biweekly | monthly | quarterly | annual | irregular
    avg_interval_days: float
    occurrences: int
    last_date: str            # ISO date of most recent charge
    next_estimated: str | None  # ISO date estimate, or None if unpredictable
    is_auto: bool             # True = auto-detected; False = user override
    confidence: float         # 0.0–1.0


def _median(values: list[float]) -> float:
    """Simple median without numpy."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def _classify_frequency(avg_days: float) -> str:
    """Map an average interval in days to a human-friendly frequency label."""
    for label, lo, hi in _FREQ_RANGES:
        if lo <= avg_days <= hi:
            return label
    return "irregular"


def _estimate_next(last_date_str: str, avg_days: float) -> str | None:
    """Estimate the next charge date from the last occurrence + avg interval."""
    try:
        last = datetime.date.fromisoformat(last_date_str)
        nxt = last + datetime.timedelta(days=round(avg_days))
        return nxt.isoformat()
    except Exception:
        return None


def detect_recurring(conn, *, include_overrides: bool = True) -> list[dict[str, Any]]:
    """Run recurring detection against ``transactions_norm``.

    Returns a list of dicts suitable for JSON serialisation, one per
    detected recurring merchant group.

    Parameters
    ----------
    conn : duckdb connection
        Open DuckDB connection (read-only is fine).
    include_overrides : bool
        When True, user overrides from ``recurring_overrides`` are merged in,
        taking precedence over auto-detection results.
    """
    # ── 1.  Group transactions by normalized merchant ────────────────────
    rows = conn.execute("""
        SELECT merchant,
               transaction_date,
               ABS(amount) AS abs_amount
        FROM   transactions_norm
        WHERE  merchant IS NOT NULL
          AND  merchant != ''
        ORDER  BY merchant, transaction_date
    """).fetchall()

    # Build per-merchant lists: {merchant: [(date_str, abs_amount), ...]}
    groups: dict[str, list[tuple[str, float]]] = {}
    for merchant, txn_date, abs_amt in rows:
        groups.setdefault(merchant, []).append((str(txn_date), float(abs_amt)))

    # ── 2.  Analyse each group ───────────────────────────────────────────
    auto_results: dict[str, RecurringPattern] = {}

    for merchant, txns in groups.items():
        if len(txns) < MIN_OCCURRENCES:
            continue

        # Deduplicate dates (same merchant + same day = one occurrence)
        # so that e.g. two Amazon charges on the same day don't inflate count
        dates = sorted(set(t[0] for t in txns))
        if len(dates) < MIN_OCCURRENCES:
            continue

        # Compute intervals between consecutive unique dates
        date_objs = [datetime.date.fromisoformat(d) for d in dates]
        intervals = [(date_objs[i + 1] - date_objs[i]).days for i in range(len(date_objs) - 1)]

        if not intervals:
            continue

        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            continue

        # Interval regularity check (coefficient of variation)
        variance = sum((d - avg_interval) ** 2 for d in intervals) / len(intervals)
        std_dev = variance ** 0.5
        cv = std_dev / avg_interval if avg_interval > 0 else 999

        if cv > MAX_INTERVAL_CV:
            continue

        # Amount consistency check
        amounts = [t[1] for t in txns]
        med_amount = _median(amounts)
        if med_amount > 0:
            amt_variance = sum((a - med_amount) ** 2 for a in amounts) / len(amounts)
            amt_cv = (amt_variance ** 0.5) / med_amount
        else:
            amt_cv = 0.0

        if amt_cv > MAX_AMOUNT_CV:
            continue

        freq = _classify_frequency(avg_interval)
        # Confidence score: scales linearly with occurrences (saturates at 6)
        # and penalises interval jitter.  A 6+ hit pattern with CV=0 → 1.0.
        confidence = min(1.0, (len(dates) / 6.0)) * (1.0 - cv)

        last_date = dates[-1]
        next_est = _estimate_next(last_date, avg_interval)

        auto_results[merchant] = RecurringPattern(
            merchant=merchant,
            median_amount=round(med_amount, 2),
            frequency=freq,
            avg_interval_days=round(avg_interval, 1),
            occurrences=len(dates),
            last_date=last_date,
            next_estimated=next_est,
            is_auto=True,
            confidence=round(confidence, 2),
        )

    # ── 3.  Merge user overrides ─────────────────────────────────────────
    overrides: dict[str, bool] = {}
    if include_overrides:
        try:
            ov_rows = conn.execute(
                "SELECT merchant_key, is_recurring FROM recurring_overrides"
            ).fetchall()
            overrides = {r[0]: r[1] for r in ov_rows}
        except Exception:
            pass

    results: list[dict[str, Any]] = []

    # Auto-detected entries — skip any the user has explicitly unmarked.
    # Note: `is False` (not `not`) is intentional — we only skip when the
    # user has set is_recurring=False, not when the key is simply absent.
    for merchant, pat in auto_results.items():
        if overrides.get(merchant) is False:
            continue
        results.append(_pattern_to_dict(pat))

    # User-marked entries not in auto-detection
    for merchant, is_rec in overrides.items():
        if not is_rec:
            continue
        if merchant in auto_results:
            continue  # already included above

        # Build a minimal pattern from the transaction data
        txns = groups.get(merchant, [])
        if not txns:
            continue
        dates = sorted(set(t[0] for t in txns))
        amounts = [t[1] for t in txns]
        med_amount = _median(amounts)

        if len(dates) >= 2:
            date_objs = [datetime.date.fromisoformat(d) for d in dates]
            intervals = [(date_objs[i + 1] - date_objs[i]).days for i in range(len(date_objs) - 1)]
            avg_interval = sum(intervals) / len(intervals) if intervals else 30
            freq = _classify_frequency(avg_interval)
            next_est = _estimate_next(dates[-1], avg_interval)
        else:
            avg_interval = 30
            freq = "monthly"
            next_est = _estimate_next(dates[-1], 30) if dates else None

        results.append(_pattern_to_dict(RecurringPattern(
            merchant=merchant,
            median_amount=round(med_amount, 2),
            frequency=freq,
            avg_interval_days=round(avg_interval, 1),
            occurrences=len(dates),
            last_date=dates[-1] if dates else "",
            next_estimated=next_est,
            is_auto=False,
            confidence=1.0,
        )))

    # Sort by median amount descending (biggest subscriptions first)
    results.sort(key=lambda r: r["median_amount"], reverse=True)
    return results


def _pattern_to_dict(p: RecurringPattern) -> dict[str, Any]:
    return {
        "merchant": p.merchant,
        "median_amount": p.median_amount,
        "frequency": p.frequency,
        "avg_interval_days": p.avg_interval_days,
        "occurrences": p.occurrences,
        "last_date": p.last_date,
        "next_estimated": p.next_estimated,
        "is_auto": p.is_auto,
        "confidence": p.confidence,
    }


def compute_monthly_recurring_total(patterns: list[dict[str, Any]]) -> float:
    """Estimate total monthly cost from a list of recurring patterns.

    Converts each pattern's median_amount to a monthly equivalent based
    on its detected frequency.
    """
    multipliers = {
        "weekly": 52 / 12,
        "biweekly": 26 / 12,
        "monthly": 1.0,
        "quarterly": 1 / 3,
        "annual": 1 / 12,
        "irregular": 1.0,  # assume monthly as fallback
    }
    total = 0.0
    for p in patterns:
        mult = multipliers.get(p.get("frequency", "monthly"), 1.0)
        total += p.get("median_amount", 0) * mult
    return round(total, 2)
