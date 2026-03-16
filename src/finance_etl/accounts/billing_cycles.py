"""Billing cycle operations: statement recording, status transitions."""
from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_billing_cycle(conn, data: dict) -> dict:
    """Record a new billing statement for an account."""
    now = _now_iso()
    conn.execute(
        """INSERT INTO ap_billing_cycles (
            account_id, cycle_label, statement_open_date, statement_close_date,
            statement_balance, minimum_payment, payment_due_date,
            status, total_paid, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', 0, ?, ?)""",
        [
            data["account_id"], data["cycle_label"],
            data.get("statement_open_date"), data.get("statement_close_date"),
            float(data["statement_balance"]),
            float(data["minimum_payment"]) if data.get("minimum_payment") is not None else None,
            data["payment_due_date"],
            now, now,
        ],
    )
    row = conn.execute(
        "SELECT id FROM ap_billing_cycles WHERE account_id = ? AND cycle_label = ?",
        [data["account_id"], data["cycle_label"]],
    ).fetchone()

    # Update nw_accounts with statement info
    conn.execute(
        """UPDATE nw_accounts SET
            last_statement_balance = ?,
            last_statement_issue_date = ?,
            minimum_payment_amount = ?,
            next_payment_due_date = ?,
            updated_at = ?
        WHERE id = ?""",
        [
            float(data["statement_balance"]),
            data.get("statement_close_date"),
            float(data["minimum_payment"]) if data.get("minimum_payment") is not None else None,
            data["payment_due_date"],
            now,
            data["account_id"],
        ],
    )

    return get_billing_cycle(conn, row[0])


def get_billing_cycle(conn, cycle_id: int) -> dict | None:
    """Get a single billing cycle by ID."""
    cols = conn.execute("SELECT * FROM ap_billing_cycles LIMIT 0").description
    col_names = [c[0] for c in cols]
    row = conn.execute("SELECT * FROM ap_billing_cycles WHERE id = ?", [cycle_id]).fetchone()
    if not row:
        return None
    return dict(zip(col_names, row))


def list_cycles_for_account(conn, account_id: int) -> list[dict]:
    """Get all billing cycles for an account, most recent first."""
    cols = conn.execute("SELECT * FROM ap_billing_cycles LIMIT 0").description
    col_names = [c[0] for c in cols]
    rows = conn.execute(
        "SELECT * FROM ap_billing_cycles WHERE account_id = ? ORDER BY cycle_label DESC",
        [account_id],
    ).fetchall()
    return [dict(zip(col_names, r)) for r in rows]


def update_billing_cycle(conn, cycle_id: int, data: dict) -> dict:
    """Update a billing cycle (correct statement balance, etc.)."""
    now = _now_iso()
    updates = {k: v for k, v in data.items() if v is not None}
    if not updates:
        return get_billing_cycle(conn, cycle_id)
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [cycle_id]
    conn.execute(f"UPDATE ap_billing_cycles SET {set_clause} WHERE id = ?", values)
    return get_billing_cycle(conn, cycle_id)


def get_open_cycles(conn) -> list[dict]:
    """Get all open/unpaid billing cycles across all accounts."""
    cols = conn.execute("SELECT * FROM ap_billing_cycles LIMIT 0").description
    col_names = [c[0] for c in cols]
    rows = conn.execute(
        """SELECT bc.* FROM ap_billing_cycles bc
        JOIN nw_accounts a ON bc.account_id = a.id
        WHERE bc.status IN ('open', 'paid_minimum')
        AND (a.status = 'active' OR a.status IS NULL)
        ORDER BY bc.payment_due_date ASC""",
    ).fetchall()
    return [dict(zip(col_names, r)) for r in rows]


def get_overdue_cycles(conn) -> list[dict]:
    """Get all overdue billing cycles."""
    cols = conn.execute("SELECT * FROM ap_billing_cycles LIMIT 0").description
    col_names = [c[0] for c in cols]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT * FROM ap_billing_cycles
        WHERE status IN ('open', 'paid_minimum')
        AND payment_due_date < ?
        ORDER BY payment_due_date ASC""",
        [today],
    ).fetchall()
    # Mark as overdue
    conn.execute(
        """UPDATE ap_billing_cycles SET status = 'overdue', updated_at = ?
        WHERE status IN ('open', 'paid_minimum') AND payment_due_date < ?""",
        [_now_iso(), today],
    )
    return [dict(zip(col_names, r)) for r in rows]


def update_cycle_payment_status(conn, cycle_id: int) -> dict:
    """Recalculate billing cycle status based on total_paid vs statement_balance."""
    cycle = get_billing_cycle(conn, cycle_id)
    if not cycle:
        return None
    now = _now_iso()
    total_paid = float(cycle["total_paid"] or 0)
    stmt_bal = float(cycle["statement_balance"])
    min_pay = float(cycle["minimum_payment"] or 0)

    if total_paid >= stmt_bal:
        new_status = "paid_full"
    elif min_pay > 0 and total_paid >= min_pay:
        if total_paid >= stmt_bal:
            new_status = "paid_statement"
        else:
            new_status = "paid_minimum"
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if cycle["payment_due_date"] < today:
            new_status = "overdue"
        else:
            new_status = "open"

    conn.execute(
        "UPDATE ap_billing_cycles SET status = ?, updated_at = ? WHERE id = ?",
        [new_status, now, cycle_id],
    )
    return get_billing_cycle(conn, cycle_id)
