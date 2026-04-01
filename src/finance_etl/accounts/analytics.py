"""Analytics: trends, projections, utilization, interest cost, annual fees, benefits."""
from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_balance_trends(conn, account_id: int, limit: int = 24) -> list[dict]:
    """
    Balance trend for one account from ap_balance_ledger.
    Returns one point per effective_date (most recent N entries).
    """
    rows = conn.execute(
        """SELECT effective_date, current_balance, statement_balance, data_source
        FROM ap_balance_ledger
        WHERE account_id = ?
        ORDER BY effective_date DESC, id DESC
        LIMIT ?""",
        [account_id, limit],
    ).fetchall()
    return [
        {
            "date": r[0],
            "balance": float(r[1]) if r[1] is not None else 0,
            "statement_balance": float(r[2]) if r[2] is not None else None,
            "data_source": r[3],
        }
        for r in reversed(rows)  # chronological order
    ]


def get_aggregate_debt_trend(conn, months: int = 12) -> list[dict]:
    """
    Aggregate debt trend from nw_snapshots — total liabilities over time.
    Falls back to ap_balance_ledger if snapshots are sparse.
    """
    rows = conn.execute(
        """SELECT snapshot_date, total_assets, total_liab, net_worth
        FROM nw_snapshots
        ORDER BY snapshot_date DESC
        LIMIT ?""",
        [months],
    ).fetchall()
    return [
        {
            "date": r[0],
            "total_assets": float(r[1]) if r[1] is not None else 0,
            "total_liabilities": float(r[2]) if r[2] is not None else 0,
            "net_worth": float(r[3]) if r[3] is not None else 0,
        }
        for r in reversed(rows)
    ]


def get_utilization_breakdown(conn) -> list[dict]:
    """
    Credit utilization per card and aggregate.
    Only includes credit cards with a positive credit limit.
    """
    rows = conn.execute("""
        SELECT id, name, institution, last_four, balance, credit_limit
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND liability_type = 'credit_card'
        AND credit_limit > 0
        ORDER BY name
    """).fetchall()

    total_balance = 0.0
    total_limit = 0.0
    cards = []

    for r in rows:
        bal = abs(float(r[4])) if r[4] else 0
        limit_val = float(r[5])
        util = round(bal / limit_val * 100, 1) if limit_val > 0 else 0
        total_balance += bal
        total_limit += limit_val
        cards.append({
            "id": r[0], "name": r[1], "institution": r[2], "last_four": r[3],
            "balance": round(bal, 2), "credit_limit": round(limit_val, 2),
            "utilization_pct": util,
            "available_credit": round(limit_val - bal, 2),
        })

    agg_util = round(total_balance / total_limit * 100, 1) if total_limit > 0 else 0
    return {
        "cards": cards,
        "aggregate": {
            "total_balance": round(total_balance, 2),
            "total_limit": round(total_limit, 2),
            "utilization_pct": agg_util,
            "available_credit": round(total_limit - total_balance, 2),
        },
    }


def get_interest_cost(conn) -> dict:
    """
    Estimated monthly interest cost from APRs on each account.
    For revolving credit (credit cards, HELOCs), uses last_statement_balance
    as the interest-bearing balance, since interest accrues on the carried
    balance from the prior statement, not on current charges.
    For installment loans (mortgage, auto, student), uses current balance.
    """
    _REVOLVING_TYPES = {"credit_card", "line_of_credit", "heloc", "personal_debt"}

    rows = conn.execute("""
        SELECT id, name, institution, last_four, liability_type,
               balance, interest_rate, last_statement_balance
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND is_asset = FALSE
        AND interest_rate IS NOT NULL AND interest_rate > 0
        ORDER BY interest_rate DESC
    """).fetchall()

    total_monthly = 0.0
    accounts = []
    for r in rows:
        liability_type = r[4] or ""
        current_bal = abs(float(r[5])) if r[5] else 0
        apr = float(r[6])
        stmt_bal = abs(float(r[7])) if r[7] else 0
        # Use statement balance for revolving credit when available
        interest_bal = (stmt_bal if stmt_bal > 0 else current_bal) \
            if liability_type in _REVOLVING_TYPES else current_bal
        monthly_interest = round(interest_bal * apr / 100.0 / 12.0, 2)
        total_monthly += monthly_interest
        accounts.append({
            "id": r[0], "name": r[1], "institution": r[2], "last_four": r[3],
            "liability_type": liability_type, "balance": round(current_bal, 2),
            "apr": apr, "monthly_interest": monthly_interest,
            "annual_interest": round(monthly_interest * 12, 2),
        })

    return {
        "accounts": accounts,
        "total_monthly_interest": round(total_monthly, 2),
        "total_annual_interest": round(total_monthly * 12, 2),
    }


def get_payoff_projection(conn, strategy: str = "minimum") -> list[dict]:
    """
    Simplified payoff projection for each liability.
    Strategies: 'minimum' (min payment), 'statement' (statement balance),
    'aggressive' (2x minimum or statement, whichever is higher).

    Returns estimated months to payoff and total interest (simplified).
    """
    # Revolving credit types where bal*0.1 is a reasonable aggressive floor.
    # Installment loans (mortgage, auto, student) have fixed amortisation
    # schedules where 10% of balance per month is wildly unrealistic.
    _REVOLVING_TYPES = {"credit_card", "line_of_credit", "heloc", "personal_debt"}

    rows = conn.execute("""
        SELECT id, name, institution, liability_type,
               balance, interest_rate, minimum_payment_amount,
               last_statement_balance, monthly_payment
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND is_asset = FALSE
        AND ABS(balance) > 0
        ORDER BY name
    """).fetchall()

    results = []
    for r in rows:
        bal = abs(float(r[4])) if r[4] else 0
        apr = float(r[5]) if r[5] else 0
        min_pay = float(r[6]) if r[6] else 0
        stmt_bal = abs(float(r[7])) if r[7] else 0
        monthly_pay = float(r[8]) if r[8] else 0
        liability_type = r[3] or ""

        # For minimum strategy, prefer minimum_payment_amount, then monthly_payment
        # (fixed recurring payment), then statement balance, then full balance.
        if strategy == "minimum":
            payment = (min_pay or monthly_pay or stmt_bal or bal)
        elif strategy == "statement":
            payment = stmt_bal if stmt_bal > 0 else bal
        elif strategy == "aggressive":
            # bal*0.1 floor only applies to revolving credit — for installment
            # loans it produces absurdly short projections.
            if liability_type in _REVOLVING_TYPES:
                payment = max(min_pay * 2, stmt_bal, bal * 0.1)
            else:
                base = max(min_pay, monthly_pay)
                payment = max(base * 2, stmt_bal) if (base > 0 or stmt_bal > 0) else bal
        else:
            payment = min_pay if min_pay > 0 else bal

        if payment <= 0:
            payment = bal  # pay off in one shot

        # Simple amortization: iterate monthly
        remaining = bal
        monthly_rate = apr / 100.0 / 12.0
        months = 0
        total_interest = 0.0
        max_months = 360  # 30 year cap

        while remaining > 0.01 and months < max_months:
            interest = remaining * monthly_rate
            total_interest += interest
            principal = min(payment - interest, remaining)
            if principal <= 0:
                # Payment doesn't cover interest — will never pay off
                months = max_months
                break
            remaining -= principal
            months += 1

        results.append({
            "id": r[0], "name": r[1], "institution": r[2],
            "liability_type": r[3], "balance": round(bal, 2),
            "apr": apr, "monthly_payment": round(payment, 2),
            "months_to_payoff": months if months < max_months else None,
            "total_interest": round(total_interest, 2),
            "total_cost": round(bal + total_interest, 2),
        })

    return results


def get_payoff_comparison(conn, extra_monthly: float = 0.0) -> dict:
    """
    Avalanche vs Snowball debt payoff comparison.

    Avalanche: attack highest-APR debt first.
    Snowball: attack lowest-balance debt first.
    Extra minimums freed when a debt is paid off roll forward to the next focus debt.

    Returns both strategies' attack order, total months, total interest, and
    the interest saved by choosing avalanche over snowball.
    """
    rows = conn.execute("""
        SELECT id, name, institution, liability_type,
               balance, interest_rate, minimum_payment_amount, monthly_payment
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND is_asset = FALSE
        AND ABS(balance) > 0
        ORDER BY name
    """).fetchall()

    debts = []
    for r in rows:
        bal = abs(float(r[4])) if r[4] else 0
        apr = float(r[5]) if r[5] else 0
        min_pay = float(r[6]) if r[6] else 0
        monthly_pay = float(r[7]) if r[7] else 0
        base = min_pay or monthly_pay or max(bal * 0.02, 10.0)
        debts.append({
            "id": r[0], "name": r[1], "institution": r[2],
            "liability_type": r[3],
            "balance": round(bal, 2),
            "apr": apr,
            "base_payment": round(base, 2),
        })

    def _simulate(ordered):
        remaining = [d["balance"] for d in ordered]
        rates = [d["apr"] / 100.0 / 12.0 for d in ordered]
        bases = [d["base_payment"] for d in ordered]
        total_interest = 0.0
        months = 0
        rolling_extra = extra_monthly

        while any(r > 0.01 for r in remaining) and months < 360:
            months += 1
            for i in range(len(remaining)):
                if remaining[i] < 0.01:
                    continue
                interest = remaining[i] * rates[i]
                total_interest += interest
                remaining[i] += interest
                payment = min(bases[i], remaining[i])
                remaining[i] = max(remaining[i] - payment, 0)
                if remaining[i] < 0.01:
                    remaining[i] = 0
                    rolling_extra += bases[i]
            for i in range(len(remaining)):
                if remaining[i] > 0.01:
                    pay = min(rolling_extra, remaining[i])
                    remaining[i] = max(remaining[i] - pay, 0)
                    rolling_extra -= pay
                    if remaining[i] < 0.01:
                        remaining[i] = 0
                        rolling_extra += bases[i]
                    break

        return (months if months < 360 else None), round(total_interest, 2)

    def _order_summary(ordered):
        return [{"id": d["id"], "name": d["name"], "balance": d["balance"],
                 "apr": d["apr"], "base_payment": d["base_payment"]}
                for d in ordered]

    av_order = sorted(debts, key=lambda d: d["apr"], reverse=True)
    sw_order = sorted(debts, key=lambda d: d["balance"])
    av_months, av_interest = _simulate(av_order)
    sw_months, sw_interest = _simulate(sw_order)
    interest_saved = round(sw_interest - av_interest, 2)

    return {
        "extra_monthly": extra_monthly,
        "total_debts": len(debts),
        "avalanche": {
            "order": _order_summary(av_order),
            "total_months": av_months,
            "total_interest": av_interest,
        },
        "snowball": {
            "order": _order_summary(sw_order),
            "total_months": sw_months,
            "total_interest": sw_interest,
        },
        "interest_saved_by_avalanche": interest_saved,
        "recommendation": "avalanche" if interest_saved > 0 else "snowball" if interest_saved < 0 else "equal",
    }


def get_annual_fees(conn) -> dict:
    """
    Annual fee calendar: which accounts have fees and when.
    Returns per-account and total annual cost.
    """
    rows = conn.execute("""
        SELECT id, name, institution, last_four, liability_type,
               annual_fee, annual_fee_month
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND annual_fee IS NOT NULL AND annual_fee > 0
        ORDER BY annual_fee_month NULLS LAST, name
    """).fetchall()

    month_names = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    total = 0.0
    accounts = []
    by_month = {i + 1: [] for i in range(12)}

    for r in rows:
        fee = float(r[5])
        month = int(r[6]) if r[6] else None
        total += fee
        entry = {
            "id": r[0], "name": r[1], "institution": r[2],
            "last_four": r[3], "liability_type": r[4],
            "annual_fee": round(fee, 2),
            "fee_month": month,
            "fee_month_name": month_names[month - 1] if month else "Unknown",
        }
        accounts.append(entry)
        if month:
            by_month[month].append(entry)

    # Summarize by month
    monthly_totals = []
    for m in range(1, 13):
        month_total = sum(e["annual_fee"] for e in by_month[m])
        monthly_totals.append({
            "month": m,
            "month_name": month_names[m - 1],
            "total": round(month_total, 2),
            "count": len(by_month[m]),
        })

    return {
        "accounts": accounts,
        "total_annual_fees": round(total, 2),
        "by_month": monthly_totals,
    }


def get_benefits_value(conn) -> dict:
    """
    Total annual value of card benefits from ap_card_benefits.
    Returns per-account benefit breakdown and ROI vs annual fees.
    Amount is stored per-occurrence; frequency determines annualization:
      monthly=x12, quarterly=x4, annual=x1 (default).
    """
    rows = conn.execute("""
        SELECT b.account_id, a.name, a.institution, a.last_four,
               a.annual_fee,
               b.benefit_name, b.amount, b.frequency, b.benefit_type
        FROM ap_card_benefits b
        JOIN nw_accounts a ON b.account_id = a.id
        WHERE (a.status = 'active' OR a.status IS NULL)
        ORDER BY a.name, b.benefit_name
    """).fetchall()

    freq_mult = {"monthly": 12, "quarterly": 4, "annual": 1}
    acct_map = {}
    for r in rows:
        aid = r[0]
        if aid not in acct_map:
            acct_map[aid] = {
                "id": aid, "name": r[1], "institution": r[2],
                "last_four": r[3],
                "annual_fee": float(r[4]) if r[4] else 0,
                "benefits": [], "total_benefit_value": 0,
            }
        per_occurrence = float(r[6]) if r[6] else 0
        freq = r[7] or "annual"
        annual_val = per_occurrence * freq_mult.get(freq, 1)
        acct_map[aid]["benefits"].append({
            "name": r[5], "annual_value": round(annual_val, 2),
            "benefit_type": r[8], "frequency": freq,
        })
        acct_map[aid]["total_benefit_value"] += annual_val

    accounts = []
    total_benefits = 0.0
    total_fees = 0.0
    for a in acct_map.values():
        a["total_benefit_value"] = round(a["total_benefit_value"], 2)
        a["roi"] = round(
            a["total_benefit_value"] / a["annual_fee"], 2
        ) if a["annual_fee"] > 0 else None
        total_benefits += a["total_benefit_value"]
        total_fees += a["annual_fee"]
        accounts.append(a)

    return {
        "accounts": accounts,
        "total_benefit_value": round(total_benefits, 2),
        "total_annual_fees": round(total_fees, 2),
        "aggregate_roi": round(total_benefits / total_fees, 2) if total_fees > 0 else None,
    }


def get_upcoming_due(conn, days: int = 14) -> list[dict]:
    """
    Accounts with payments due in the next N days.
    Uses next_payment_due_date or computes from due_day.
    """
    today = _today()
    rows = conn.execute(f"""
        SELECT id, name, institution, last_four, liability_type,
               balance, last_statement_balance, minimum_payment_amount,
               due_day, next_payment_due_date, autopay_enabled
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND is_asset = FALSE
        AND (
            (next_payment_due_date IS NOT NULL
             AND CAST(next_payment_due_date AS DATE) >= CAST(? AS DATE)
             AND CAST(next_payment_due_date AS DATE) <= CAST(? AS DATE) + INTERVAL '{int(days)} days')
            OR (next_payment_due_date IS NULL AND due_day IS NOT NULL)
        )
        ORDER BY next_payment_due_date ASC NULLS LAST, due_day ASC
    """, [today, today]).fetchall()

    results = []
    for r in rows:
        results.append({
            "id": r[0], "name": r[1], "institution": r[2], "last_four": r[3],
            "liability_type": r[4],
            "balance": float(r[5]) if r[5] else 0,
            "statement_balance": float(r[6]) if r[6] else None,
            "minimum_payment": float(r[7]) if r[7] else None,
            "due_day": r[8],
            "next_payment_due_date": r[9],
            "autopay_enabled": r[10],
        })
    return results


def get_payment_history_summary(conn, months: int = 6) -> dict:
    """
    Payment history aggregated by month for charts.
    """
    rows = conn.execute("""
        SELECT
            STRFTIME(CAST(payment_date AS DATE), '%Y-%m') AS month,
            COUNT(*) AS payment_count,
            SUM(amount) AS total_amount
        FROM ap_payments
        GROUP BY STRFTIME(CAST(payment_date AS DATE), '%Y-%m')
        ORDER BY month DESC
        LIMIT ?
    """, [months]).fetchall()

    return [
        {
            "month": r[0],
            "count": r[1],
            "total": round(float(r[2]), 2) if r[2] else 0,
        }
        for r in reversed(rows)
    ]
