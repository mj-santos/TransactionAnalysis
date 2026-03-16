"""API routes for the Accounts & Liabilities module."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Query

from . import router
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
