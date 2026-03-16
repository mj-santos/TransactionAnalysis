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
from .crud import (
    COA_TAXONOMY,
    create_account,
    create_payment_source_tag,
    delete_payment_source_tag,
    get_account,
    list_accounts,
    list_payment_source_tags,
    soft_delete_account,
    update_account,
)
from .schemas import (
    AccountCreate,
    AccountStatusUpdate,
    AccountUpdate,
    BulkBalanceUpdateRequest,
    PaymentSourceTagCreate,
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
