"""Balance operations: bulk update, ledger inserts, stale detection, snapshots."""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def bulk_balance_update(conn, updates: list[dict]) -> dict:
    """
    Process a list of balance updates. Each entry:
      { account_id, current_balance, statement_balance?, minimum_payment?, data_source? }

    Creates ap_balance_ledger rows, updates nw_accounts.balance + last_verified_at.
    Returns summary of changes.
    """
    now = _now_iso()
    today = _today()
    changed = 0

    for entry in updates:
        account_id = entry["account_id"]
        current_balance = float(entry["current_balance"])
        statement_balance = entry.get("statement_balance")
        minimum_payment = entry.get("minimum_payment")
        data_source = entry.get("data_source", "manual")

        # Insert ledger row (immutable history)
        conn.execute(
            """INSERT INTO ap_balance_ledger (
                account_id, observed_at, effective_date, current_balance,
                statement_balance, minimum_payment, data_source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                account_id, now, today, current_balance,
                float(statement_balance) if statement_balance is not None else None,
                float(minimum_payment) if minimum_payment is not None else None,
                data_source, now,
            ],
        )

        # Update nw_accounts
        set_parts = ["balance = ?", "last_verified_at = ?", "updated_at = ?"]
        params = [current_balance, now, now]

        if statement_balance is not None:
            set_parts.append("last_statement_balance = ?")
            params.append(float(statement_balance))
        if minimum_payment is not None:
            set_parts.append("minimum_payment_amount = ?")
            params.append(float(minimum_payment))

        params.append(account_id)
        conn.execute(
            f"UPDATE nw_accounts SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        changed += 1

    return {"updated": changed, "timestamp": now}


def get_balance_history(conn, account_id: int, limit: int = 100) -> list[dict]:
    """Get balance ledger entries for one account, most recent first."""
    cols = conn.execute(
        "SELECT * FROM ap_balance_ledger WHERE account_id = ? LIMIT 0",
        [account_id],
    ).description
    col_names = [c[0] for c in cols]
    rows = conn.execute(
        "SELECT * FROM ap_balance_ledger WHERE account_id = ? "
        "ORDER BY effective_date DESC, id DESC LIMIT ?",
        [account_id, limit],
    ).fetchall()
    return [dict(zip(col_names, r)) for r in rows]


def get_latest_balances(conn) -> list[dict]:
    """Get the latest balance for every account (most recent ledger entry)."""
    rows = conn.execute("""
        SELECT a.id, a.name, a.acct_type, a.balance, a.is_asset,
               a.account_class, a.liability_type, a.asset_type,
               a.institution, a.last_four, a.credit_limit,
               a.last_statement_balance, a.minimum_payment_amount,
               a.due_day, a.status, a.last_verified_at,
               a.payment_source_tag, a.interest_rate, a.annual_fee
        FROM nw_accounts a
        WHERE a.status != 'closed' OR a.status IS NULL
        ORDER BY a.account_class, a.account_code, a.name
    """).fetchall()
    cols = [
        "id", "name", "acct_type", "balance", "is_asset",
        "account_class", "liability_type", "asset_type",
        "institution", "last_four", "credit_limit",
        "last_statement_balance", "minimum_payment_amount",
        "due_day", "status", "last_verified_at",
        "payment_source_tag", "interest_rate", "annual_fee",
    ]
    return [dict(zip(cols, r)) for r in rows]


def get_stale_accounts(conn, days: int = 7) -> list[dict]:
    """Get accounts not updated in more than N days."""
    rows = conn.execute(f"""
        SELECT id, name, acct_type, balance, is_asset,
               account_class, liability_type, asset_type,
               institution, status, last_verified_at
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND (
            last_verified_at IS NULL
            OR CAST(last_verified_at AS TIMESTAMP) < CURRENT_TIMESTAMP - INTERVAL '{int(days)} days'
        )
        ORDER BY last_verified_at ASC NULLS FIRST
    """).fetchall()
    cols = [
        "id", "name", "acct_type", "balance", "is_asset",
        "account_class", "liability_type", "asset_type",
        "institution", "status", "last_verified_at",
    ]
    return [dict(zip(cols, r)) for r in rows]


def generate_snapshot(conn) -> dict:
    """
    Generate a net worth snapshot from current nw_accounts balances.
    Inserts into nw_snapshots and returns the snapshot data.
    """
    now = _now_iso()
    today = _today()

    rows = conn.execute(
        "SELECT id, name, acct_type, balance, is_asset FROM nw_accounts"
    ).fetchall()

    total_assets = 0.0
    total_liab = 0.0
    detail = []

    for r in rows:
        acct_id, name, acct_type, balance, is_asset = r
        bal = float(balance) if balance else 0.0
        if is_asset:
            total_assets += bal
        else:
            total_liab += abs(bal)
        detail.append({
            "id": acct_id, "name": name, "acct_type": acct_type,
            "balance": bal, "is_asset": is_asset,
        })

    net = round(total_assets - total_liab, 2)

    conn.execute(
        "INSERT INTO nw_snapshots (snapshot_date, total_assets, total_liab, net_worth, detail_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [today, round(total_assets, 2), round(total_liab, 2), net, json.dumps(detail), now],
    )

    return {
        "snapshot_date": today,
        "total_assets": round(total_assets, 2),
        "total_liabilities": round(total_liab, 2),
        "net_worth": net,
    }


def get_overview_summary(conn) -> dict:
    """
    Compute KPI summary for the Overview sub-view:
    total liabilities, total assets, net position, credit utilization,
    due this week count, estimated monthly interest.
    """
    # Totals — split assets into liquid cash vs investments
    row = conn.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN is_asset = TRUE THEN balance ELSE 0 END), 0) AS total_assets,
            COALESCE(SUM(CASE WHEN is_asset = TRUE AND asset_type IN ('checking', 'savings', 'digital_wallet')
                         THEN balance ELSE 0 END), 0) AS cash_at_hand,
            COALESCE(SUM(CASE WHEN is_asset = TRUE AND asset_type = 'investment'
                         THEN balance ELSE 0 END), 0) AS total_investments,
            COALESCE(SUM(CASE WHEN is_asset = FALSE THEN ABS(balance) ELSE 0 END), 0) AS total_liabilities,
            COALESCE(SUM(CASE WHEN is_asset = FALSE AND liability_type != 'personal_debt'
                         THEN ABS(balance) ELSE 0 END), 0) AS total_liab_excl_personal
        FROM nw_accounts
        WHERE status = 'active' OR status IS NULL
    """).fetchone()

    total_assets = float(row[0])
    cash_at_hand = float(row[1])
    total_investments = float(row[2])
    total_liabilities = float(row[3])
    total_liab_excl = float(row[4])

    # Credit utilization
    cc_row = conn.execute("""
        SELECT
            COALESCE(SUM(ABS(balance)), 0),
            COALESCE(SUM(credit_limit), 0)
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND liability_type = 'credit_card'
        AND credit_limit > 0
    """).fetchone()
    cc_balance = float(cc_row[0])
    cc_limit = float(cc_row[1])
    utilization = round((cc_balance / cc_limit * 100), 1) if cc_limit > 0 else 0

    # Due this week (accounts with due_day within next 7 days)
    today_day = datetime.now(timezone.utc).day
    # Simple approach: count accounts where due_day is within 7 days of today
    due_this_week = conn.execute("""
        SELECT COUNT(*) FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND is_asset = FALSE
        AND due_day IS NOT NULL
        AND (
            (due_day >= ? AND due_day <= ?)
            OR (? > 24 AND due_day <= ?)
        )
    """, [today_day, today_day + 7, today_day, (today_day + 7) % 31]).fetchone()[0]

    # Estimated monthly interest (CC balances * APR / 12)
    interest_row = conn.execute("""
        SELECT COALESCE(SUM(ABS(balance) * COALESCE(interest_rate, 0) / 100.0 / 12.0), 0)
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND is_asset = FALSE
        AND interest_rate IS NOT NULL AND interest_rate > 0
    """).fetchone()
    est_monthly_interest = round(float(interest_row[0]), 2)

    return {
        "total_assets": round(total_assets, 2),
        "cash_at_hand": round(cash_at_hand, 2),
        "total_investments": round(total_investments, 2),
        "total_liabilities": round(total_liabilities, 2),
        "total_liabilities_excl_personal": round(total_liab_excl, 2),
        "net_position": round(total_assets - total_liabilities, 2),
        "liquid_net": round(cash_at_hand - total_liab_excl, 2),
        "credit_utilization_pct": utilization,
        "cc_balance": round(cc_balance, 2),
        "cc_limit": round(cc_limit, 2),
        "due_this_week": due_this_week,
        "est_monthly_interest": est_monthly_interest,
    }
