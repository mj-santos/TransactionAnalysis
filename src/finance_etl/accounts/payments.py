"""Payment recording and history."""
from __future__ import annotations

from datetime import datetime, timezone

from .billing_cycles import get_billing_cycle, update_cycle_payment_status


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_payment(conn, data: dict) -> dict:
    """
    Record a payment from an asset account to a liability account.
    Optionally links to a billing cycle and updates its total_paid.
    """
    now = _now_iso()
    amount = float(data["amount"])

    conn.execute(
        """INSERT INTO ap_payments (
            from_account_id, to_account_id, billing_cycle_id,
            payment_date, amount, payment_type, confirmation_ref,
            status, notes, data_source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)""",
        [
            data["from_account_id"], data["to_account_id"],
            data.get("billing_cycle_id"),
            data["payment_date"], amount,
            data.get("payment_type", "manual"),
            data.get("confirmation_ref"),
            data.get("status", "pending"),
            data.get("notes"),
            now, now,
        ],
    )

    row = conn.execute(
        "SELECT id FROM ap_payments ORDER BY id DESC LIMIT 1"
    ).fetchone()
    payment_id = row[0]

    # Update billing cycle total_paid if linked
    if data.get("billing_cycle_id"):
        cycle_id = data["billing_cycle_id"]
        conn.execute(
            """UPDATE ap_billing_cycles
            SET total_paid = total_paid + ?, updated_at = ?
            WHERE id = ?""",
            [amount, now, cycle_id],
        )
        update_cycle_payment_status(conn, cycle_id)

    # Update payment plan status to in_progress
    cycle_month = data["payment_date"][:7]  # 'YYYY-MM'
    conn.execute(
        """UPDATE ap_payment_plan
        SET status = 'in_progress', updated_at = ?
        WHERE liability_id = ? AND cycle_month = ? AND status = 'planned'""",
        [now, data["to_account_id"], cycle_month],
    )

    # Update last_payment fields on the liability account
    conn.execute(
        """UPDATE nw_accounts SET
            last_payment_date = ?, last_payment_amount = ?, updated_at = ?
        WHERE id = ?""",
        [data["payment_date"], amount, now, data["to_account_id"]],
    )

    return get_payment(conn, payment_id)


def get_payment(conn, payment_id: int) -> dict | None:
    """Get a single payment by ID."""
    cols = conn.execute("SELECT * FROM ap_payments LIMIT 0").description
    col_names = [c[0] for c in cols]
    row = conn.execute("SELECT * FROM ap_payments WHERE id = ?", [payment_id]).fetchone()
    if not row:
        return None
    return dict(zip(col_names, row))


def get_payment_history(conn, account_id: int | None = None, limit: int = 100) -> list[dict]:
    """Get payment history, optionally filtered by account (either from or to)."""
    cols = conn.execute("SELECT * FROM ap_payments LIMIT 0").description
    col_names = [c[0] for c in cols]

    if account_id:
        rows = conn.execute(
            """SELECT * FROM ap_payments
            WHERE from_account_id = ? OR to_account_id = ?
            ORDER BY payment_date DESC, id DESC LIMIT ?""",
            [account_id, account_id, limit],
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ap_payments ORDER BY payment_date DESC, id DESC LIMIT ?",
            [limit],
        ).fetchall()

    return [dict(zip(col_names, r)) for r in rows]
