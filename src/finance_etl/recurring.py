"""Recurring transaction detection engine.

Analyzes transaction history to identify recurring charges by grouping on
normalized merchant name and looking for regular intervals (weekly, monthly,
annual) with consistent amounts.  A pattern is flagged as recurring only when
it has appeared 3+ times.

User overrides (manual mark/unmark) are stored in the ``recurring_overrides``
DB table and take precedence over auto-detection.

Annual fee keyword detection (``detect_annual_fee_suggestions``) supplements
the interval-based algorithm by scanning descriptions for membership/renewal
keywords and correlating card-specific fees with the importing account.
"""
from __future__ import annotations

import datetime
import hashlib
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
    paused: bool = False      # True = user paused this charge


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
    override_details: dict[str, dict] = {}  # merchant_key -> {label, amount, frequency, paused, last_date}
    if include_overrides:
        try:
            ov_rows = conn.execute(
                "SELECT merchant_key, is_recurring, label, amount, frequency, "
                "       paused, last_date, next_estimated "
                "FROM recurring_overrides"
            ).fetchall()
            for r in ov_rows:
                overrides[r[0]] = r[1]
                override_details[r[0]] = {
                    "label": r[2], "amount": r[3], "frequency": r[4],
                    "paused": bool(r[5]) if r[5] is not None else False,
                    "last_date": r[6],
                    "next_estimated": r[7],
                }
        except Exception:
            pass

    results: list[dict[str, Any]] = []

    # Auto-detected entries — skip any the user has explicitly unmarked.
    # Note: `is False` (not `not`) is intentional — we only skip when the
    # user has set is_recurring=False, not when the key is simply absent.
    for merchant, pat in auto_results.items():
        if overrides.get(merchant) is False:
            continue
        # Apply user overrides for pause, dates
        details = override_details.get(merchant, {})
        pat.paused = details.get("paused", False)
        if details.get("last_date"):
            pat.last_date = details["last_date"]
        if details.get("next_estimated"):
            pat.next_estimated = details["next_estimated"]
        elif details.get("last_date"):
            # Recompute next_estimated from overridden last_date
            pat.next_estimated = _estimate_next(details["last_date"], pat.avg_interval_days) or pat.next_estimated
        results.append(_pattern_to_dict(pat))

    # User-marked entries not in auto-detection
    for merchant, is_rec in overrides.items():
        if not is_rec:
            continue
        if merchant in auto_results:
            continue  # already included above

        # Build a minimal pattern from the transaction data
        txns = groups.get(merchant, [])
        details = override_details.get(merchant, {})
        is_paused = details.get("paused", False)

        user_next_est = details.get("next_estimated")

        if txns:
            dates = sorted(set(t[0] for t in txns))
            amounts = [t[1] for t in txns]
            med_amount = _median(amounts)
            effective_last = details.get("last_date") or (dates[-1] if dates else "")

            if len(dates) >= 2:
                date_objs = [datetime.date.fromisoformat(d) for d in dates]
                intervals = [(date_objs[i + 1] - date_objs[i]).days for i in range(len(date_objs) - 1)]
                avg_interval = sum(intervals) / len(intervals) if intervals else 30
                freq = _classify_frequency(avg_interval)
                next_est = user_next_est or _estimate_next(effective_last, avg_interval)
            else:
                avg_interval = 30
                freq = details.get("frequency") or "monthly"
                next_est = user_next_est or (_estimate_next(effective_last, 30) if effective_last else None)

            results.append(_pattern_to_dict(RecurringPattern(
                merchant=merchant,
                median_amount=round(med_amount, 2),
                frequency=freq,
                avg_interval_days=round(avg_interval, 1),
                occurrences=len(dates),
                last_date=effective_last,
                next_estimated=next_est,
                is_auto=False,
                confidence=1.0,
                paused=is_paused,
            )))
        else:
            # No matching transactions — use stored override data
            # (e.g. accepted annual fee suggestion where merchant_key = label)
            stored_freq = details.get("frequency") or "annual"
            stored_amount = details.get("amount")
            stored_last_date = details.get("last_date") or ""
            freq_days = {"annual": 365, "quarterly": 90, "monthly": 30,
                         "biweekly": 14, "weekly": 7}
            avg_interval = float(freq_days.get(stored_freq, 365))
            next_est = user_next_est or (_estimate_next(stored_last_date, avg_interval) if stored_last_date else None)

            results.append(_pattern_to_dict(RecurringPattern(
                merchant=merchant,
                median_amount=round(float(stored_amount), 2) if stored_amount else 0.0,
                frequency=stored_freq,
                avg_interval_days=avg_interval,
                occurrences=0,
                last_date=stored_last_date,
                next_estimated=next_est,
                is_auto=False,
                confidence=1.0,
                paused=is_paused,
            )))

    # Sort by median amount descending (biggest subscriptions first)
    results.sort(key=lambda r: r["median_amount"], reverse=True)

    # Partition into active and paused
    active = [r for r in results if not r.get("paused")]
    paused = [r for r in results if r.get("paused")]
    return active, paused


_MONTHLY_MULTIPLIERS: dict[str, float] = {
    "weekly":    52 / 12,
    "biweekly":  26 / 12,
    "monthly":   1.0,
    "quarterly": 1 / 3,
    "annual":    1 / 12,
    "yearly":    1 / 12,
    "irregular": 1.0,
}


def _pattern_to_dict(p: RecurringPattern) -> dict[str, Any]:
    mult = _MONTHLY_MULTIPLIERS.get(p.frequency, 1.0)
    monthly_equiv = round(p.median_amount * mult, 2)
    return {
        "merchant": p.merchant,
        "median_amount": p.median_amount,
        "monthly_equivalent": monthly_equiv,
        "frequency": p.frequency,
        "avg_interval_days": p.avg_interval_days,
        "occurrences": p.occurrences,
        "last_date": p.last_date,
        "next_estimated": p.next_estimated,
        "is_auto": p.is_auto,
        "confidence": p.confidence,
        "paused": p.paused,
    }


def compute_monthly_recurring_total(patterns: list[dict[str, Any]]) -> float:
    """Estimate total monthly cost from a list of recurring patterns.

    Uses pre-computed ``monthly_equivalent`` if present, otherwise falls back
    to multiplying median_amount by the frequency multiplier.
    """
    total = 0.0
    for p in patterns:
        if "monthly_equivalent" in p:
            total += p["monthly_equivalent"]
        else:
            mult = _MONTHLY_MULTIPLIERS.get(p.get("frequency", "monthly"), 1.0)
            total += p.get("median_amount", 0) * mult
    return round(total, 2)


# ---------------------------------------------------------------------------
# Annual fee / membership keyword detection
# ---------------------------------------------------------------------------

# (keyword_pattern, label_template)
# Card-specific fees use {account} placeholder filled from account_name.
_ANNUAL_FEE_KEYWORDS: list[tuple[str, str]] = [
    # Card-specific fees
    ("renewal membership fee", "{account} Annual Fee"),
    ("annual membership fee", "{account} Annual Fee"),
    ("annual card fee", "{account} Annual Fee"),
    ("annual fee", "{account} Annual Fee"),
    ("membership fee", "{account} Membership Fee"),
    # Known annual subscriptions
    ("amazon prime", "Amazon Prime"),
    ("prime membership", "Amazon Prime"),
    ("costco membership", "Costco Membership"),
    ("costco annual", "Costco Membership"),
    ("sam's club membership", "Sam's Club Membership"),
    ("walmart+ annual", "Walmart+ Annual"),
    ("aaa membership", "AAA Membership"),
    ("netflix annual", "Netflix Annual"),
    ("youtube premium annual", "YouTube Premium Annual"),
    ("spotify annual", "Spotify Annual"),
    ("apple one annual", "Apple One Annual"),
    ("icloud annual", "iCloud Annual"),
    ("microsoft 365", "Microsoft 365"),
    ("office 365", "Microsoft 365"),
    ("adobe annual", "Adobe Annual"),
    ("creative cloud annual", "Adobe Creative Cloud"),
]

# Keywords that represent card-specific fees (use {account} placeholder)
_CARD_FEE_KEYWORDS = frozenset({
    "renewal membership fee", "annual membership fee", "annual fee",
    "annual card fee", "membership fee",
})


def _suggestion_id(keyword: str, account_name: str) -> str:
    """Deterministic ID for a suggestion based on keyword + account."""
    raw = f"{keyword.lower().strip()}|{account_name.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def detect_annual_fee_suggestions(
    conn,
    dismissed_ids: set[str] | None = None,
    existing_override_keys: set[str] | None = None,
    auto_annual_merchants: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan transactions for annual fee / membership keywords.

    Returns suggested annual charges that the user can accept, edit, or dismiss.
    Excludes suggestions already dismissed, already in overrides, or already
    auto-detected as annual by the interval engine.

    Parameters
    ----------
    conn : duckdb connection
    dismissed_ids : set of suggestion IDs the user has dismissed
    existing_override_keys : set of merchant_key values in recurring_overrides
    auto_annual_merchants : set of merchant names auto-detected as annual
    """
    dismissed = dismissed_ids or set()
    override_keys = existing_override_keys or set()
    auto_annual = auto_annual_merchants or set()

    # Build OR condition for all keywords
    like_clauses = []
    params = []
    for kw, _label in _ANNUAL_FEE_KEYWORDS:
        like_clauses.append("LOWER(description) LIKE ?")
        params.append(f"%{kw}%")

    if not like_clauses:
        return []

    where = " OR ".join(like_clauses)
    rows = conn.execute(
        f"""SELECT transaction_fingerprint, description, ABS(amount) AS abs_amount,
                   transaction_date, bank_name, account_name, merchant
            FROM transactions_norm
            WHERE ({where})
              AND COALESCE(excluded, FALSE) = FALSE
            ORDER BY transaction_date DESC""",
        params,
    ).fetchall()

    # Group matches by (matched_keyword, account_name)
    # Each group produces one suggestion
    groups: dict[tuple[str, str], list[dict]] = {}
    for fp, desc, amt, txn_date, bank, account, merchant in rows:
        desc_lower = desc.lower() if desc else ""
        # Find the first matching keyword
        matched_kw = None
        matched_label = None
        for kw, label_tpl in _ANNUAL_FEE_KEYWORDS:
            if kw in desc_lower:
                matched_kw = kw
                matched_label = label_tpl
                break
        if not matched_kw:
            continue

        acct = account or bank or "Unknown"
        key = (matched_kw, acct)
        groups.setdefault(key, []).append({
            "fingerprint": fp,
            "description": desc,
            "amount": float(amt),
            "date": str(txn_date),
            "bank_name": bank or "",
            "account_name": acct,
            "merchant": merchant or "",
            "keyword": matched_kw,
            "label_template": matched_label,
        })

    # Build suggestion list
    suggestions = []
    for (keyword, account), txns in groups.items():
        sid = _suggestion_id(keyword, account)

        # Skip if dismissed
        if sid in dismissed:
            continue

        # Build label
        is_card_fee = keyword in _CARD_FEE_KEYWORDS
        label_tpl = txns[0]["label_template"]
        label = label_tpl.replace("{account}", account) if is_card_fee else label_tpl

        # Skip if label already in overrides or auto-detected as annual
        label_lower = label.lower()
        if any(label_lower == k.lower() for k in override_keys):
            continue
        # Also check if the merchant is in overrides
        merchant = txns[0]["merchant"]
        if merchant and any(merchant.lower() == k.lower() for k in override_keys):
            continue
        if merchant and merchant in auto_annual:
            continue

        # Most recent transaction is the reference
        latest = txns[0]  # already sorted DESC
        next_est = None
        try:
            last_dt = datetime.date.fromisoformat(latest["date"][:10])
            next_dt = last_dt + datetime.timedelta(days=365)
            next_est = next_dt.isoformat()
        except (ValueError, TypeError):
            pass

        suggestions.append({
            "suggestion_id": sid,
            "label": label,
            "description": latest["description"],
            "amount": latest["amount"],
            "account_name": account,
            "bank_name": latest["bank_name"],
            "merchant": merchant,
            "last_date": latest["date"][:10] if latest["date"] else "",
            "next_estimated": next_est,
            "frequency": "annual",
            "match_count": len(txns),
            "is_card_fee": is_card_fee,
        })

    # Sort by amount descending (biggest fees first)
    suggestions.sort(key=lambda s: s["amount"], reverse=True)
    return suggestions
