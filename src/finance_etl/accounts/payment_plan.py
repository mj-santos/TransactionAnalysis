"""Payment plan operations: assignment matrix, capacity calculations, rollforward."""
from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_cycle() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_payment_plan(conn, cycle_month: str) -> list[dict]:
    """Get all payment plan assignments for a given cycle month."""
    cols = conn.execute("SELECT * FROM ap_payment_plan LIMIT 0").description
    col_names = [c[0] for c in cols]
    rows = conn.execute(
        """SELECT pp.* FROM ap_payment_plan pp
        JOIN nw_accounts a ON pp.liability_id = a.id
        WHERE pp.cycle_month = ?
        AND (a.status = 'active' OR a.status IS NULL)
        ORDER BY a.account_code, a.name""",
        [cycle_month],
    ).fetchall()
    return [dict(zip(col_names, r)) for r in rows]


def upsert_plan_assignment(conn, data: dict) -> dict:
    """Create or update a payment plan assignment."""
    now = _now_iso()
    liability_id = data["liability_id"]
    cycle_month = data["cycle_month"]

    existing = conn.execute(
        "SELECT id FROM ap_payment_plan WHERE liability_id = ? AND cycle_month = ?",
        [liability_id, cycle_month],
    ).fetchone()

    planned_amount = float(data["planned_amount"]) if data.get("planned_amount") is not None else None

    if existing:
        conn.execute(
            """UPDATE ap_payment_plan SET
                source_id = ?, planned_amount = ?, strategy = ?,
                status = ?, notes = ?, updated_at = ?
            WHERE id = ?""",
            [
                data["source_id"], planned_amount,
                data.get("strategy", "statement"),
                data.get("status", "planned"),
                data.get("notes"),
                now, existing[0],
            ],
        )
        plan_id = existing[0]
    else:
        conn.execute(
            """INSERT INTO ap_payment_plan (
                liability_id, source_id, cycle_month, planned_amount,
                strategy, status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                liability_id, data["source_id"], cycle_month,
                planned_amount,
                data.get("strategy", "statement"),
                data.get("status", "planned"),
                data.get("notes"),
                now, now,
            ],
        )
        row = conn.execute(
            "SELECT id FROM ap_payment_plan WHERE liability_id = ? AND cycle_month = ?",
            [liability_id, cycle_month],
        ).fetchone()
        plan_id = row[0]

    return _get_plan_by_id(conn, plan_id)


def _get_plan_by_id(conn, plan_id: int) -> dict | None:
    cols = conn.execute("SELECT * FROM ap_payment_plan LIMIT 0").description
    col_names = [c[0] for c in cols]
    row = conn.execute("SELECT * FROM ap_payment_plan WHERE id = ?", [plan_id]).fetchone()
    if not row:
        return None
    return dict(zip(col_names, row))


def rollforward_plan(conn, from_month: str, to_month: str) -> dict:
    """Copy payment assignments from one month to another."""
    now = _now_iso()
    prev_plans = conn.execute(
        "SELECT liability_id, source_id, strategy, notes, planned_amount FROM ap_payment_plan WHERE cycle_month = ?",
        [from_month],
    ).fetchall()

    created = 0
    skipped = 0
    for row in prev_plans:
        liability_id, source_id, strategy, notes, prev_planned_amount = row
        existing = conn.execute(
            "SELECT id FROM ap_payment_plan WHERE liability_id = ? AND cycle_month = ?",
            [liability_id, to_month],
        ).fetchone()
        if existing:
            skipped += 1
            continue

        # Derive planned_amount for the new cycle.
        # - statement/minimum/full_balance: re-derive from current account state
        # - fixed/extra_principal: user-specified amounts — carry forward from previous cycle
        acct = conn.execute(
            "SELECT last_statement_balance, minimum_payment_amount, balance FROM nw_accounts WHERE id = ?",
            [liability_id],
        ).fetchone()
        planned_amount = None
        if acct:
            stmt_bal = float(acct[0]) if acct[0] else None
            min_pay = float(acct[1]) if acct[1] else None
            balance = float(acct[2]) if acct[2] else None
            if strategy == "minimum" and min_pay:
                planned_amount = min_pay
            elif strategy == "statement" and stmt_bal:
                planned_amount = stmt_bal
            elif strategy == "full_balance" and balance:
                planned_amount = abs(balance)
            elif strategy in ("fixed", "extra_principal") and prev_planned_amount is not None:
                planned_amount = float(prev_planned_amount)

        conn.execute(
            """INSERT INTO ap_payment_plan (
                liability_id, source_id, cycle_month, planned_amount,
                strategy, status, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, ?)""",
            [liability_id, source_id, to_month, planned_amount, strategy, notes, now, now],
        )
        created += 1

    return {"created": created, "skipped": skipped, "from_month": from_month, "to_month": to_month}


def get_capacity(conn, cycle_month: str | None = None) -> list[dict]:
    """
    Per-asset capacity: current balance - total allocated for the cycle.
    Returns one row per asset account.
    """
    if not cycle_month:
        cycle_month = _current_cycle()

    rows = conn.execute("""
        SELECT
            a.id, a.name, a.acct_type, a.balance, a.institution,
            a.asset_type, a.payment_source_tag,
            COALESCE(alloc.total_allocated, 0) AS total_allocated
        FROM nw_accounts a
        LEFT JOIN (
            SELECT source_id, SUM(COALESCE(planned_amount, 0)) AS total_allocated
            FROM ap_payment_plan
            WHERE cycle_month = ?
            AND status != 'skipped'
            GROUP BY source_id
        ) alloc ON a.id = alloc.source_id
        WHERE a.is_asset = TRUE
        AND (a.status = 'active' OR a.status IS NULL)
        ORDER BY a.name
    """, [cycle_month]).fetchall()

    result = []
    for r in rows:
        balance = float(r[3]) if r[3] else 0.0
        allocated = float(r[7])
        remaining = round(balance - allocated, 2)
        result.append({
            "id": r[0], "name": r[1], "acct_type": r[2],
            "balance": round(balance, 2), "institution": r[4],
            "asset_type": r[5], "payment_source_tag": r[6],
            "total_allocated": round(allocated, 2),
            "remaining_after_payments": remaining,
        })
    return result
