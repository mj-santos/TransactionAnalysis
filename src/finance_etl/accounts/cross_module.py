"""Cross-module integration: read-only queries against transactions_norm.

All functions here are read-only and do not modify the transactions data.
They bridge the Accounts module with the existing Spendly transaction engine.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spending_vs_statement(conn, account_id: int, cycle_label: str) -> dict | None:
    """
    Compare CC spending from transactions_norm against a billing cycle's
    statement_balance. Flag discrepancy > 5%.

    Requires the nw_account to have linked_account_id and linked_bank_name set,
    which maps to transactions_norm.account_id and bank_name.
    """
    # Get the billing cycle
    cycle = conn.execute(
        """SELECT statement_balance, statement_open_date, statement_close_date
        FROM ap_billing_cycles
        WHERE account_id = ? AND cycle_label = ?""",
        [account_id, cycle_label],
    ).fetchone()
    if not cycle:
        return None

    stmt_bal = float(cycle[0]) if cycle[0] else 0
    open_date = cycle[1]
    close_date = cycle[2]

    if not open_date or not close_date:
        return {"error": "Billing cycle missing open/close dates", "discrepancy": None}

    # Get the linked transaction account
    acct = conn.execute(
        "SELECT linked_account_id, linked_bank_name, name FROM nw_accounts WHERE id = ?",
        [account_id],
    ).fetchone()
    if not acct or not acct[0]:
        return {"error": "Account not linked to transaction data", "discrepancy": None}

    linked_account_id = acct[0]
    linked_bank_name = acct[1]

    # Sum spending from transactions_norm for the billing period
    query = """
        SELECT COALESCE(SUM(ABS(amount)), 0)
        FROM transactions_norm
        WHERE account_id = ?
        AND transaction_date >= CAST(? AS DATE)
        AND transaction_date <= CAST(? AS DATE)
        AND statement_type = 'credit_card'
    """
    params = [linked_account_id, open_date, close_date]
    if linked_bank_name:
        query += " AND bank_name = ?"
        params.append(linked_bank_name)

    row = conn.execute(query, params).fetchone()
    txn_total = float(row[0]) if row else 0

    discrepancy = abs(txn_total - stmt_bal)
    discrepancy_pct = round(discrepancy / stmt_bal * 100, 1) if stmt_bal > 0 else 0
    flagged = discrepancy_pct > 5.0

    return {
        "account_id": account_id,
        "account_name": acct[2],
        "cycle_label": cycle_label,
        "statement_balance": round(stmt_bal, 2),
        "transaction_total": round(txn_total, 2),
        "discrepancy": round(discrepancy, 2),
        "discrepancy_pct": discrepancy_pct,
        "flagged": flagged,
    }


def verify_payment(conn, payment_id: int) -> dict:
    """
    Cross-reference an ap_payments entry against bank transactions in
    transactions_norm. Match criteria: amount ± $0.01, date ± 3 days,
    matching account_id from linked nw_account.

    If matched, sets verified = TRUE and verified_fingerprint on ap_payments.
    """
    payment = conn.execute(
        "SELECT * FROM ap_payments WHERE id = ?", [payment_id]
    ).fetchone()
    if not payment:
        return {"error": "Payment not found", "verified": False}

    cols = [c[0] for c in conn.execute("SELECT * FROM ap_payments LIMIT 0").description]
    pay = dict(zip(cols, payment))

    # Get the source (from) account's linked transaction info
    source = conn.execute(
        "SELECT linked_account_id, linked_bank_name FROM nw_accounts WHERE id = ?",
        [pay["from_account_id"]],
    ).fetchone()
    if not source or not source[0]:
        return {"error": "Source account not linked to transaction data", "verified": False}

    amount = float(pay["amount"])
    payment_date = pay["payment_date"]

    # Search for matching transaction
    matches = conn.execute(
        """SELECT transaction_fingerprint, transaction_date, amount, merchant, description
        FROM transactions_norm
        WHERE account_id = ?
        AND ABS(ABS(amount) - ?) <= 0.01
        AND ABS(DATEDIFF('day', CAST(transaction_date AS DATE), CAST(? AS DATE))) <= 3
        ORDER BY ABS(DATEDIFF('day', CAST(transaction_date AS DATE), CAST(? AS DATE))) ASC
        LIMIT 5""",
        [source[0], amount, payment_date, payment_date],
    ).fetchall()

    if not matches:
        return {
            "payment_id": payment_id,
            "verified": False,
            "candidates": 0,
            "message": "No matching transaction found",
        }

    # Use the best match (closest date)
    best = matches[0]
    fingerprint = best[0]

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE ap_payments SET verified = TRUE, verified_fingerprint = ?, updated_at = ? WHERE id = ?",
        [fingerprint, now, payment_id],
    )

    return {
        "payment_id": payment_id,
        "verified": True,
        "matched_fingerprint": fingerprint,
        "matched_date": str(best[1]),
        "matched_amount": float(best[2]),
        "matched_description": best[4],
        "candidates": len(matches),
    }


def suggested_liabilities(conn, min_amount: float = 20.0) -> list[dict]:
    """
    Surface recurring charges from transactions_norm as suggested liability
    accounts. Looks for recurring merchants with monthly frequency and
    consistent amounts that don't already have a matching nw_account.

    Only suggests charges above min_amount to filter out subscriptions
    that aren't worth tracking as separate liability accounts.
    """
    # Get all recurring merchants from transactions_norm
    # Group by merchant, look for monthly-ish patterns
    rows = conn.execute("""
        SELECT merchant,
               COUNT(*) AS occurrences,
               ROUND(AVG(ABS(amount)), 2) AS avg_amount,
               ROUND(STDDEV(ABS(amount)), 2) AS stddev_amount,
               MAX(transaction_date) AS last_date,
               MIN(transaction_date) AS first_date,
               account_name
        FROM transactions_norm
        WHERE merchant IS NOT NULL
        AND merchant != ''
        AND statement_type = 'credit_card'
        AND transaction_subtype = 'spending'
        GROUP BY merchant, account_name
        HAVING COUNT(*) >= 3
        AND AVG(ABS(amount)) >= ?
        ORDER BY AVG(ABS(amount)) DESC
    """, [min_amount]).fetchall()

    # Get existing account names for dedup
    existing = conn.execute(
        "SELECT LOWER(name) FROM nw_accounts WHERE is_asset = FALSE"
    ).fetchall()
    existing_names = {r[0] for r in existing}

    suggestions = []
    seen_merchants = set()
    for r in rows:
        merchant = r[0]
        merchant_lower = merchant.lower()

        # Skip if already tracked or already suggested
        if merchant_lower in existing_names or merchant_lower in seen_merchants:
            continue
        seen_merchants.add(merchant_lower)

        occurrences = r[1]
        avg_amount = float(r[2])
        stddev = float(r[3]) if r[3] else 0
        last_date = str(r[4])
        first_date = str(r[5])

        # Check if it's monthly-ish: at least 3 occurrences, low variance
        cv = stddev / avg_amount if avg_amount > 0 else 0
        if cv > 0.3:
            continue  # Too variable

        suggestions.append({
            "merchant": merchant,
            "avg_amount": avg_amount,
            "occurrences": occurrences,
            "frequency": "monthly",
            "last_date": last_date,
            "first_date": first_date,
            "account_name": r[6],
            "suggestion": f"You pay ~${avg_amount:.2f}/mo to {merchant}",
        })

    return suggestions


def get_utilization_alerts(conn, threshold: float = 30.0) -> list[dict]:
    """
    Surface credit cards with utilization above the FICO threshold (default 30%).
    Returns alerts suitable for Dashboard display.
    """
    rows = conn.execute("""
        SELECT id, name, institution, last_four,
               ABS(balance) AS balance, credit_limit
        FROM nw_accounts
        WHERE (status = 'active' OR status IS NULL)
        AND liability_type = 'credit_card'
        AND credit_limit > 0
        AND ABS(balance) / credit_limit * 100 > ?
        ORDER BY ABS(balance) / credit_limit DESC
    """, [threshold]).fetchall()

    return [
        {
            "id": r[0], "name": r[1], "institution": r[2], "last_four": r[3],
            "balance": round(float(r[4]), 2),
            "credit_limit": round(float(r[5]), 2),
            "utilization_pct": round(float(r[4]) / float(r[5]) * 100, 1),
            "severity": "critical" if float(r[4]) / float(r[5]) > 0.8 else "warning",
            "message": f"{r[1]}: {round(float(r[4]) / float(r[5]) * 100, 1)}% utilization",
        }
        for r in rows
    ]


def get_balance_card_data(conn, linked_account_id: str, linked_bank_name: str | None = None) -> dict | None:
    """
    Get balance card data for a transaction account by its linked IDs.
    Returns the nw_accounts data needed for the balance card display
    in the Credit Cards / Bank Transactions tabs.
    """
    query = """
        SELECT id, name, institution, last_four, balance,
               credit_limit, interest_rate, liability_type, asset_type,
               account_class, last_verified_at, data_source,
               last_statement_balance, minimum_payment_amount,
               last_statement_issue_date, status
        FROM nw_accounts
        WHERE linked_account_id = ?
        AND (status = 'active' OR status IS NULL)
    """
    params = [linked_account_id]
    if linked_bank_name:
        query += " AND linked_bank_name = ?"
        params.append(linked_bank_name)
    query += " LIMIT 1"

    row = conn.execute(query, params).fetchone()
    if not row:
        return None

    last_verified = row[10]
    staleness = None
    staleness_level = "fresh"
    if last_verified:
        from datetime import datetime, timezone
        try:
            verified_dt = datetime.fromisoformat(last_verified)
            now = datetime.now(timezone.utc)
            days_ago = (now - verified_dt).days
            staleness = days_ago
            if days_ago > 14:
                staleness_level = "stale"
            elif days_ago > 7:
                staleness_level = "aging"
        except (ValueError, TypeError):
            pass

    return {
        "id": row[0],
        "name": row[1],
        "institution": row[2],
        "last_four": row[3],
        "balance": round(float(row[4]), 2) if row[4] else 0,
        "credit_limit": round(float(row[5]), 2) if row[5] else None,
        "interest_rate": round(float(row[6]), 4) if row[6] else None,
        "liability_type": row[7],
        "asset_type": row[8],
        "account_class": row[9],
        "last_verified_at": last_verified,
        "data_source": row[11] or "manual",
        "statement_balance": round(float(row[12]), 2) if row[12] else None,
        "minimum_payment": round(float(row[13]), 2) if row[13] else None,
        "last_statement_date": row[14],
        "status": row[15] or "active",
        "staleness_days": staleness,
        "staleness_level": staleness_level,
    }


def get_linkable_sources(conn) -> list[dict]:
    """
    Return distinct transaction sources (account_id + bank_name pairs)
    from transactions_norm that could be linked to nw_accounts.
    Also indicates which are already linked.
    """
    try:
        rows = conn.execute("""
            SELECT DISTINCT t.account_id, t.bank_name, t.statement_type,
                   COUNT(*) AS txn_count
            FROM transactions_norm t
            WHERE t.account_id IS NOT NULL
            GROUP BY t.account_id, t.bank_name, t.statement_type
            ORDER BY t.bank_name, t.account_id
        """).fetchall()
    except Exception:
        return []

    # Get existing links
    linked = conn.execute(
        "SELECT linked_account_id, linked_bank_name, id, name FROM nw_accounts WHERE linked_account_id IS NOT NULL"
    ).fetchall()
    linked_map = {(r[0], r[1]): {"nw_id": r[2], "nw_name": r[3]} for r in linked}

    sources = []
    for r in rows:
        acct_id, bank_name, stmt_type, count = r[0], r[1], r[2], r[3]
        link_info = linked_map.get((acct_id, bank_name))
        sources.append({
            "account_id": acct_id,
            "bank_name": bank_name,
            "statement_type": stmt_type,
            "txn_count": count,
            "linked_to": link_info,
        })

    return sources


def annual_fee_cross_reference(conn) -> list[dict]:
    """
    Cross-reference annual fees in nw_accounts with detected annual fee
    transactions in transactions_norm. Flag discrepancies.

    Matches by looking for transactions on the linked account that look
    like annual fees (large positive amounts that match nw_accounts.annual_fee).
    """
    rows = conn.execute("""
        SELECT a.id, a.name, a.institution, a.annual_fee, a.annual_fee_month,
               a.linked_account_id, a.linked_bank_name
        FROM nw_accounts a
        WHERE (a.status = 'active' OR a.status IS NULL)
        AND a.annual_fee IS NOT NULL AND a.annual_fee > 0
        ORDER BY a.name
    """).fetchall()

    results = []
    for r in rows:
        acct_id, name, institution, expected_fee, fee_month = r[0], r[1], r[2], float(r[3]), r[4]
        linked_acct = r[5]

        entry = {
            "id": acct_id, "name": name, "institution": institution,
            "expected_fee": round(expected_fee, 2),
            "fee_month": fee_month,
            "detected_fee": None,
            "discrepancy": None,
            "status": "no_link" if not linked_acct else "no_match",
        }

        if linked_acct:
            # Search for a matching fee transaction in the last 13 months
            fee_txns = conn.execute("""
                SELECT amount, transaction_date, description
                FROM transactions_norm
                WHERE account_id = ?
                AND ABS(ABS(amount) - ?) <= 5.00
                AND transaction_date >= CURRENT_DATE - INTERVAL '13 months'
                ORDER BY transaction_date DESC
                LIMIT 1
            """, [linked_acct, expected_fee]).fetchall()

            if fee_txns:
                detected = abs(float(fee_txns[0][0]))
                disc = abs(detected - expected_fee)
                entry["detected_fee"] = round(detected, 2)
                entry["discrepancy"] = round(disc, 2)
                entry["detected_date"] = str(fee_txns[0][1])
                entry["detected_description"] = fee_txns[0][2]
                entry["status"] = "mismatch" if disc > 1.0 else "matched"

        results.append(entry)

    return results
