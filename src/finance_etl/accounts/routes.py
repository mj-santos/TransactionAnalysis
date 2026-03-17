"""API routes for the Accounts & Liabilities module."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Query

from . import router
from .balance_ops import (
    bulk_balance_update,
    generate_snapshot,
    get_balance_history,
    get_latest_balances,
    get_overview_summary,
    get_stale_accounts,
)
from .billing_cycles import (
    create_billing_cycle,
    get_open_cycles,
    get_overdue_cycles,
    list_cycles_for_account,
    update_billing_cycle,
)
from .crud import (
    COA_TAXONOMY,
    bulk_delete_accounts,
    create_account,
    create_payment_source_tag,
    delete_payment_source_tag,
    get_account,
    get_delete_impact,
    hard_delete_account,
    list_accounts,
    list_payment_source_tags,
    soft_delete_account,
    update_account,
)
from .payment_plan import (
    get_capacity,
    get_payment_plan,
    rollforward_plan,
    upsert_plan_assignment,
)
from .import_wizard import (
    commit_import,
    detect_file,
    infer_account_type,
    preview_import,
    read_csv_rows,
    read_xlsx_sheet,
    suggest_account_mappings,
)
from .cross_module import (
    annual_fee_cross_reference,
    get_balance_card_data,
    get_linkable_sources,
    get_utilization_alerts,
    spending_vs_statement,
    suggested_liabilities,
    verify_payment,
)
from .analytics import (
    get_aggregate_debt_trend,
    get_annual_fees,
    get_balance_trends,
    get_benefits_value,
    get_interest_cost,
    get_payoff_projection,
    get_payment_history_summary,
    get_upcoming_due,
    get_utilization_breakdown,
)
from .payments import (
    get_payment_history,
    record_payment,
)
from .schemas import (
    AccountCreate,
    AccountStatusUpdate,
    AccountUpdate,
    BillingCycleCreate,
    BulkDeleteRequest,
    BillingCycleUpdate,
    BulkBalanceUpdateRequest,
    PaymentCreate,
    PaymentSourceTagCreate,
    PlanAssignment,
    PlanBulkRequest,
    PlanRollforwardRequest,
)


def _get_conn():
    from finance_etl.db import get_connection
    return get_connection("data/db/finance.duckdb")


# ── Account CRUD ─────────────────────────────────────────────────────────

@router.get("/", summary="List all accounts with filters")
def route_list_accounts(
    account_class: Optional[str] = Query(None),
    liability_type: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    institution: Optional[str] = Query(None),
):
    filters = {}
    if account_class:
        filters["account_class"] = account_class
    if liability_type:
        filters["liability_type"] = liability_type
    if asset_type:
        filters["asset_type"] = asset_type
    if status:
        filters["status"] = status
    if institution:
        filters["institution"] = institution

    conn = _get_conn()
    try:
        accounts = list_accounts(conn, filters if filters else None)
        return {"accounts": accounts, "total": len(accounts)}
    finally:
        conn.close()


@router.get("/taxonomy", summary="Return CoA tree structure")
def route_taxonomy():
    return COA_TAXONOMY


@router.get("/tags", summary="List payment source tags")
def route_list_tags():
    conn = _get_conn()
    try:
        return list_payment_source_tags(conn)
    finally:
        conn.close()


@router.post("/tags", summary="Create payment source tag", status_code=201)
def route_create_tag(payload: PaymentSourceTagCreate):
    conn = _get_conn()
    try:
        return create_payment_source_tag(conn, payload.short_code, payload.account_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.delete("/tags/{code}", summary="Delete payment source tag")
def route_delete_tag(code: str):
    conn = _get_conn()
    try:
        delete_payment_source_tag(conn, code)
        return {"ok": True}
    finally:
        conn.close()


# ── Balance Operations (must be before /{account_id} to avoid capture) ──

@router.get("/balances/latest", summary="Latest balance for all accounts")
def route_latest_balances():
    conn = _get_conn()
    try:
        return get_latest_balances(conn)
    finally:
        conn.close()


@router.get("/balances/stale", summary="Accounts not updated in > N days")
def route_stale_accounts(days: int = Query(7, ge=1)):
    conn = _get_conn()
    try:
        return get_stale_accounts(conn, days)
    finally:
        conn.close()


@router.get("/balances/snapshot", summary="Generate net worth snapshot")
def route_snapshot():
    conn = _get_conn()
    try:
        return generate_snapshot(conn)
    finally:
        conn.close()


@router.get("/balances/summary", summary="Overview KPI summary")
def route_overview_summary():
    conn = _get_conn()
    try:
        return get_overview_summary(conn)
    finally:
        conn.close()


@router.post("/balances/update", summary="Bulk balance update (monthly reconciliation)")
def route_bulk_balance_update(payload: BulkBalanceUpdateRequest):
    conn = _get_conn()
    try:
        result = bulk_balance_update(conn, [u.model_dump() for u in payload.updates])
        # Auto-generate snapshot after bulk update
        snapshot = generate_snapshot(conn)
        result["snapshot"] = snapshot
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.get("/balances/history/{account_id}", summary="Balance ledger for one account")
def route_balance_history(account_id: int, limit: int = Query(100, ge=1, le=1000)):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        return get_balance_history(conn, account_id, limit)
    finally:
        conn.close()


# ── Billing Cycles (static paths before /{account_id}) ───────────────────

@router.get("/cycles/open", summary="All open/unpaid billing cycles")
def route_open_cycles():
    conn = _get_conn()
    try:
        return get_open_cycles(conn)
    finally:
        conn.close()


@router.get("/cycles/overdue", summary="All overdue billing cycles")
def route_overdue_cycles():
    conn = _get_conn()
    try:
        return get_overdue_cycles(conn)
    finally:
        conn.close()


@router.get("/cycles/{cycle_id}", summary="Get a single billing cycle")
def route_get_cycle(cycle_id: int):
    from .billing_cycles import get_billing_cycle
    conn = _get_conn()
    try:
        cycle = get_billing_cycle(conn, cycle_id)
        if not cycle:
            raise HTTPException(status_code=404, detail="Billing cycle not found")
        return cycle
    finally:
        conn.close()


@router.put("/cycles/{cycle_id}", summary="Update a billing cycle")
def route_update_cycle(cycle_id: int, payload: BillingCycleUpdate):
    from .billing_cycles import get_billing_cycle
    conn = _get_conn()
    try:
        cycle = get_billing_cycle(conn, cycle_id)
        if not cycle:
            raise HTTPException(status_code=404, detail="Billing cycle not found")
        return update_billing_cycle(conn, cycle_id, payload.model_dump(exclude_none=True))
    finally:
        conn.close()


# ── Payment Plan & Payments (static paths before /{account_id}) ──────────

@router.get("/payments/plan/{cycle_month}", summary="Payment plan for a cycle month")
def route_get_plan(cycle_month: str):
    conn = _get_conn()
    try:
        return get_payment_plan(conn, cycle_month)
    finally:
        conn.close()


@router.post("/payments/plan", summary="Create/update payment plan assignments")
def route_upsert_plan(payload: PlanBulkRequest):
    conn = _get_conn()
    try:
        results = []
        for assignment in payload.assignments:
            results.append(upsert_plan_assignment(conn, assignment.model_dump()))
        return {"assignments": results, "total": len(results)}
    finally:
        conn.close()


@router.post("/payments/plan/rollforward", summary="Copy last month's plan forward")
def route_rollforward(payload: PlanRollforwardRequest):
    conn = _get_conn()
    try:
        return rollforward_plan(conn, payload.from_month, payload.to_month)
    finally:
        conn.close()


@router.get("/payments/capacity", summary="Per-asset remaining capacity")
def route_capacity(cycle_month: Optional[str] = Query(None)):
    conn = _get_conn()
    try:
        return get_capacity(conn, cycle_month)
    finally:
        conn.close()


@router.post("/payments/", summary="Record a payment", status_code=201)
def route_record_payment(payload: PaymentCreate):
    conn = _get_conn()
    try:
        return record_payment(conn, payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.get("/payments/history", summary="Payment history")
def route_payment_history(
    account_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    conn = _get_conn()
    try:
        return get_payment_history(conn, account_id, limit)
    finally:
        conn.close()


# ── Analytics (static paths before /{account_id}) ────────────────────────

@router.get("/analytics/trends/aggregate", summary="Aggregate debt/asset trend")
def route_aggregate_trends(months: int = Query(12, ge=1, le=60)):
    conn = _get_conn()
    try:
        return get_aggregate_debt_trend(conn, months)
    finally:
        conn.close()


@router.get("/analytics/trends/{account_id}", summary="Balance trend for one account")
def route_balance_trends(account_id: int, limit: int = Query(24, ge=1, le=120)):
    conn = _get_conn()
    try:
        return get_balance_trends(conn, account_id, limit)
    finally:
        conn.close()


@router.get("/analytics/utilization", summary="Credit utilization per card and aggregate")
def route_utilization():
    conn = _get_conn()
    try:
        return get_utilization_breakdown(conn)
    finally:
        conn.close()


@router.get("/analytics/interest-cost", summary="Estimated monthly interest from APRs")
def route_interest_cost():
    conn = _get_conn()
    try:
        return get_interest_cost(conn)
    finally:
        conn.close()


@router.get("/analytics/payoff-projection", summary="Debt payoff timeline by strategy")
def route_payoff_projection(strategy: str = Query("minimum", pattern="^(minimum|statement|aggressive)$")):
    conn = _get_conn()
    try:
        return get_payoff_projection(conn, strategy)
    finally:
        conn.close()


@router.get("/analytics/annual-fees", summary="Annual fee calendar and totals")
def route_annual_fees():
    conn = _get_conn()
    try:
        return get_annual_fees(conn)
    finally:
        conn.close()


@router.get("/analytics/benefits-value", summary="Card benefits total value and ROI")
def route_benefits_value():
    conn = _get_conn()
    try:
        return get_benefits_value(conn)
    finally:
        conn.close()


@router.get("/analytics/upcoming", summary="Accounts due in next N days")
def route_upcoming_due(days: int = Query(14, ge=1, le=90)):
    conn = _get_conn()
    try:
        return get_upcoming_due(conn, days)
    finally:
        conn.close()


@router.get("/analytics/payment-summary", summary="Payment history aggregated by month")
def route_payment_summary(months: int = Query(6, ge=1, le=24)):
    conn = _get_conn()
    try:
        return get_payment_history_summary(conn, months)
    finally:
        conn.close()


# ── Import Wizard ─────────────────────────────────────────────────────

@router.post("/import/detect", summary="Upload CSV/XLSX and detect file structure")
def route_import_detect(file_path: str = Query(...)):
    try:
        return detect_file(file_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import/suggest-mappings", summary="Suggest column mappings for a section")
def route_import_suggest(
    headers: list[str] = Query(...),
    section_type: str = Query("liability", pattern="^(liability|asset)$"),
):
    return suggest_account_mappings(headers, section_type)


@router.post("/import/preview", summary="Preview import before committing")
def route_import_preview(payload: dict):
    """
    Expects: { rows, headers, mapping, section_type, file_path?, start_row?, end_row?, sheet_name? }
    If file_path is provided with start_row/end_row or sheet_name, reads rows from file.
    Otherwise uses rows/headers from the payload directly.
    """
    conn = _get_conn()
    try:
        file_path = payload.get("file_path")
        headers = payload.get("headers", [])
        rows = payload.get("rows", [])

        if file_path and payload.get("sheet_name"):
            headers, rows = read_xlsx_sheet(file_path, payload["sheet_name"])
        elif file_path and payload.get("start_row") is not None:
            headers, rows = read_csv_rows(
                file_path,
                payload.get("start_row"),
                payload.get("end_row"),
            )

        mapping = payload.get("mapping", {})
        section_type = payload.get("section_type", "liability")

        return preview_import(rows, headers, mapping, section_type, conn)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.post("/import/commit", summary="Commit the import")
def route_import_commit(payload: dict):
    """
    Expects: { accounts: [...], duplicate_action: 'skip'|'update'|'create' }
    """
    conn = _get_conn()
    try:
        accounts = payload.get("accounts", [])
        duplicate_action = payload.get("duplicate_action", "skip")
        result = commit_import(conn, accounts, duplicate_action)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


# ── Delete Operations (static paths before /{account_id}) ─────────────

@router.get("/delete-impact/{account_id}", summary="Preview what will be deleted")
def route_delete_impact(account_id: int):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        impact = get_delete_impact(conn, account_id)
        impact["account_name"] = acct["name"]
        return impact
    finally:
        conn.close()


@router.delete("/delete/{account_id}", summary="Permanently delete an account")
def route_hard_delete(account_id: int):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        impact = hard_delete_account(conn, account_id)
        impact["account_name"] = acct["name"]
        return {"ok": True, "impact": impact}
    finally:
        conn.close()


@router.post("/bulk-delete", summary="Bulk delete accounts (soft or permanent)")
def route_bulk_delete(payload: BulkDeleteRequest):
    conn = _get_conn()
    try:
        return bulk_delete_accounts(conn, payload.account_ids, payload.permanent)
    finally:
        conn.close()


# ── Cross-Module Integration ──────────────────────────────────────────

@router.get("/integration/spending-vs-statement/{account_id}/{cycle_label}",
            summary="Compare CC spending vs statement balance")
def route_spending_vs_statement(account_id: int, cycle_label: str):
    conn = _get_conn()
    try:
        result = spending_vs_statement(conn, account_id, cycle_label)
        if not result:
            raise HTTPException(status_code=404, detail="Billing cycle not found")
        return result
    finally:
        conn.close()


@router.post("/integration/verify-payment/{payment_id}",
             summary="Cross-reference payment against bank transactions")
def route_verify_payment(payment_id: int):
    conn = _get_conn()
    try:
        return verify_payment(conn, payment_id)
    finally:
        conn.close()


@router.get("/integration/suggested-liabilities",
            summary="Recurring charges that could be liability accounts")
def route_suggested_liabilities(min_amount: float = Query(20.0, ge=0)):
    conn = _get_conn()
    try:
        return suggested_liabilities(conn, min_amount)
    finally:
        conn.close()


@router.get("/integration/utilization-alerts",
            summary="Credit cards above FICO utilization threshold")
def route_utilization_alerts(threshold: float = Query(30.0, ge=0, le=100)):
    conn = _get_conn()
    try:
        return get_utilization_alerts(conn, threshold)
    finally:
        conn.close()


@router.get("/integration/annual-fee-xref",
            summary="Cross-reference annual fees with transaction data")
def route_annual_fee_xref():
    conn = _get_conn()
    try:
        return annual_fee_cross_reference(conn)
    finally:
        conn.close()


@router.get("/integration/balance-card",
            summary="Balance card data for a linked transaction account")
def route_balance_card(
    linked_account_id: str = Query(...),
    linked_bank_name: Optional[str] = Query(None),
):
    conn = _get_conn()
    try:
        data = get_balance_card_data(conn, linked_account_id, linked_bank_name)
        if not data:
            raise HTTPException(status_code=404, detail="No linked account found")
        return data
    finally:
        conn.close()


@router.get("/integration/linkable-sources",
            summary="Transaction sources available for account linking")
def route_linkable_sources():
    conn = _get_conn()
    try:
        return get_linkable_sources(conn)
    finally:
        conn.close()


# ── Account Detail (path param routes last) ──────────────────────────────

@router.get("/{account_id}", summary="Get single account detail")
def route_get_account(account_id: int):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        return acct
    finally:
        conn.close()


@router.post("/", summary="Create a new account", status_code=201)
def route_create_account(payload: AccountCreate):
    conn = _get_conn()
    try:
        return create_account(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.put("/{account_id}", summary="Update account details")
def route_update_account(account_id: int, payload: AccountUpdate):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        return update_account(conn, account_id, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Update failed: {exc}") from exc
    finally:
        conn.close()


@router.get("/{account_id}/cycles", summary="Billing cycles for one account")
def route_account_cycles(account_id: int):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        return list_cycles_for_account(conn, account_id)
    finally:
        conn.close()


@router.post("/{account_id}/cycles", summary="Record a new billing statement", status_code=201)
def route_create_cycle(account_id: int, payload: BillingCycleCreate):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        data = payload.model_dump()
        data["account_id"] = account_id
        return create_billing_cycle(conn, data)
    except Exception as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.patch("/{account_id}/status", summary="Change account status")
def route_update_status(account_id: int, payload: AccountStatusUpdate):
    conn = _get_conn()
    try:
        acct = get_account(conn, account_id)
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        soft_delete_account(conn, account_id, payload.status)
        return get_account(conn, account_id)
    finally:
        conn.close()
