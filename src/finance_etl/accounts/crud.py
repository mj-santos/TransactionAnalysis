"""Account CRUD operations for the Accounts & Liabilities module."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .schemas import AccountCreate, AccountUpdate

# ── Chart of Accounts code ranges ────────────────────────────────────────
_COA_RANGES = {
    # asset types
    "checking":       (1110, 1119),
    "savings":        (1120, 1129),
    "digital_wallet": (1130, 1139),
    "investment":     (1210, 1219),
    # liability types
    "credit_card":    (2100, 2199),
    "mortgage":       (2210, 2219),
    "auto_loan":      (2220, 2229),
    "student_loan":   (2230, 2239),
    "utility":        (2300, 2399),
    "personal_debt":  (2400, 2499),
    "other":          (2500, 2599),
}

# Full CoA taxonomy tree (for GET /accounts/taxonomy)
COA_TAXONOMY = {
    "1000": {
        "label": "Assets",
        "children": {
            "1100": {
                "label": "Cash & Bank Accounts",
                "children": {
                    "1110": {"label": "Checking Accounts"},
                    "1120": {"label": "Savings Accounts"},
                    "1130": {"label": "Digital Wallets"},
                },
            },
            "1200": {
                "label": "Investments",
                "children": {
                    "1210": {"label": "Brokerage / Retirement"},
                },
            },
        },
    },
    "2000": {
        "label": "Liabilities",
        "children": {
            "2100": {
                "label": "Credit Cards",
                "children": {},
            },
            "2200": {
                "label": "Secured Loans",
                "children": {
                    "2210": {"label": "Mortgage"},
                    "2220": {"label": "Auto Loans"},
                    "2230": {"label": "Student Loans"},
                },
            },
            "2300": {"label": "Utilities & Services", "children": {}},
            "2400": {"label": "Personal Debts", "children": {}},
            "2500": {"label": "Other Liabilities", "children": {}},
        },
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assign_account_code(conn, account_class: str, subtype: str) -> str:
    """Auto-assign the next available CoA code for the given account type."""
    key = subtype or ("checking" if account_class == "asset" else "other")
    lo, hi = _COA_RANGES.get(key, (2500, 2599))

    row = conn.execute(
        "SELECT MAX(CAST(account_code AS INTEGER)) FROM nw_accounts "
        "WHERE account_code IS NOT NULL "
        "AND CAST(account_code AS INTEGER) BETWEEN ? AND ?",
        [lo, hi],
    ).fetchone()

    max_code = row[0] if row and row[0] is not None else None
    if max_code is not None:
        next_code = int(max_code) + 1
        if next_code > hi:
            raise ValueError(f"CoA range exhausted for {key} ({lo}-{hi})")
        return str(next_code)
    return str(lo)


def _acct_type_label(account_class: str, subtype: str | None) -> str:
    """Derive the legacy acct_type string from class + subtype."""
    if account_class == "asset":
        return subtype or "checking"
    return subtype or "other"


def create_account(conn, data: AccountCreate) -> dict:
    """Create a new account and its initial balance ledger entry."""
    now = _now_iso()
    subtype = data.asset_type if data.account_class == "asset" else data.liability_type
    account_code = _assign_account_code(conn, data.account_class, subtype)
    acct_type = _acct_type_label(data.account_class, subtype)
    is_asset = data.account_class == "asset"

    conn.execute(
        """INSERT INTO nw_accounts (
            name, acct_type, balance, is_asset, created_at, updated_at,
            account_code, account_class, liability_type, asset_type,
            institution, last_four, responsibility, open_date,
            due_day, next_payment_due_date,
            credit_limit, annual_fee, annual_fee_month,
            autopay_enabled, autopay_source_id, default_payment_source_id,
            origination_date, origination_principal, interest_rate, loan_term,
            escrow_balance, payment_source_tag,
            last_verified_at, data_source, status
        ) VALUES (
            ?,?,?,?,?,?,
            ?,?,?,?,
            ?,?,?,?,
            ?,?,
            ?,?,?,
            ?,?,?,
            ?,?,?,?,
            ?,?,
            ?,?,?
        )""",
        [
            data.name, acct_type, float(data.balance), is_asset, now, now,
            account_code, data.account_class, data.liability_type, data.asset_type,
            data.institution, data.last_four, data.responsibility, data.open_date,
            data.due_day, data.next_payment_due_date,
            float(data.credit_limit) if data.credit_limit is not None else None,
            float(data.annual_fee) if data.annual_fee is not None else None,
            data.annual_fee_month,
            data.autopay_enabled,
            data.autopay_source_id,
            data.default_payment_source_id,
            data.origination_date,
            float(data.origination_principal) if data.origination_principal is not None else None,
            float(data.interest_rate) if data.interest_rate is not None else None,
            data.loan_term,
            float(data.escrow_balance) if data.escrow_balance is not None else None,
            data.payment_source_tag,
            now, "manual", "active",
        ],
    )

    row = conn.execute(
        "SELECT id FROM nw_accounts WHERE account_code = ? ORDER BY id DESC LIMIT 1",
        [account_code],
    ).fetchone()
    account_id = row[0]

    # Create initial balance ledger entry
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO ap_balance_ledger (
            account_id, observed_at, effective_date, current_balance,
            statement_balance, available_balance, data_source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)""",
        [
            account_id, now, today,
            float(data.balance),
            float(data.statement_balance) if data.statement_balance is not None else None,
            float(data.available_balance) if data.available_balance is not None else None,
            now,
        ],
    )

    return get_account(conn, account_id)


def get_account(conn, account_id: int) -> dict | None:
    """Get a single account by ID."""
    cols = conn.execute("SELECT * FROM nw_accounts WHERE id = ?", [account_id]).description
    row = conn.execute("SELECT * FROM nw_accounts WHERE id = ?", [account_id]).fetchone()
    if not row:
        return None
    col_names = [c[0] for c in cols]
    return dict(zip(col_names, row))


def list_accounts(conn, filters: dict | None = None) -> list[dict]:
    """List accounts with optional filters."""
    clauses = ["1=1"]
    params = []
    if filters:
        if filters.get("account_class"):
            clauses.append("account_class = ?")
            params.append(filters["account_class"])
        if filters.get("liability_type"):
            clauses.append("liability_type = ?")
            params.append(filters["liability_type"])
        if filters.get("asset_type"):
            clauses.append("asset_type = ?")
            params.append(filters["asset_type"])
        if filters.get("status"):
            clauses.append("status = ?")
            params.append(filters["status"])
        if filters.get("institution"):
            clauses.append("institution = ?")
            params.append(filters["institution"])
    where = " AND ".join(clauses)
    cols = conn.execute(f"SELECT * FROM nw_accounts WHERE {where} LIMIT 0", params).description
    col_names = [c[0] for c in cols]
    rows = conn.execute(
        f"SELECT * FROM nw_accounts WHERE {where} ORDER BY account_code, name",
        params,
    ).fetchall()
    return [dict(zip(col_names, r)) for r in rows]


def update_account(conn, account_id: int, data: AccountUpdate) -> dict:
    """Update an existing account. Handles type changes with CoA re-assignment."""
    now = _now_iso()
    updates = data.model_dump(exclude_none=True)
    if not updates:
        return get_account(conn, account_id)

    # If account_class or subtype changed, re-derive acct_type, is_asset, account_code
    if "account_class" in updates or "liability_type" in updates or "asset_type" in updates:
        current = get_account(conn, account_id)
        new_class = updates.get("account_class", current["account_class"])
        new_liability_type = updates.get("liability_type", current.get("liability_type"))
        new_asset_type = updates.get("asset_type", current.get("asset_type"))

        # Determine the active subtype based on class
        if new_class == "asset":
            subtype = new_asset_type or "checking"
            updates["liability_type"] = None
        else:
            subtype = new_liability_type or "credit_card"
            updates["asset_type"] = None

        updates["acct_type"] = _acct_type_label(new_class, subtype)
        updates["is_asset"] = new_class == "asset"
        updates["account_code"] = _assign_account_code(conn, new_class, subtype)

    # Convert Decimal fields to float for DuckDB
    for key, val in updates.items():
        if isinstance(val, Decimal):
            updates[key] = float(val)
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [account_id]
    conn.execute(f"UPDATE nw_accounts SET {set_clause} WHERE id = ?", values)
    return get_account(conn, account_id)


def soft_delete_account(conn, account_id: int, new_status: str = "closed") -> bool:
    """Soft-delete an account by changing its status."""
    now = _now_iso()
    conn.execute(
        "UPDATE nw_accounts SET status = ?, updated_at = ? WHERE id = ?",
        [new_status, now, account_id],
    )
    return True


def create_payment_source_tag(conn, short_code: str, account_id: int) -> dict:
    """Create a payment source tag."""
    now = _now_iso()
    conn.execute(
        "INSERT INTO ap_payment_source_tags (short_code, account_id, created_at) VALUES (?, ?, ?)",
        [short_code, account_id, now],
    )
    return {"short_code": short_code, "account_id": account_id, "created_at": now}


def list_payment_source_tags(conn) -> list[dict]:
    """List all payment source tags."""
    rows = conn.execute(
        "SELECT short_code, account_id, created_at FROM ap_payment_source_tags ORDER BY short_code"
    ).fetchall()
    return [{"short_code": r[0], "account_id": r[1], "created_at": r[2]} for r in rows]


def delete_payment_source_tag(conn, short_code: str) -> bool:
    """Delete a payment source tag."""
    conn.execute("DELETE FROM ap_payment_source_tags WHERE short_code = ?", [short_code])
    return True
