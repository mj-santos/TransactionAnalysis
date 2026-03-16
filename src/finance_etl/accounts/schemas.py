"""Pydantic models for the Accounts & Liabilities module."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── Account CRUD ─────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    account_class: str = Field(..., pattern="^(asset|liability)$")
    # Liability subtypes
    liability_type: Optional[str] = None
    # Asset subtypes
    asset_type: Optional[str] = None

    institution: Optional[str] = None
    last_four: Optional[str] = None
    responsibility: Optional[str] = None
    open_date: Optional[str] = None

    # Billing
    due_day: Optional[int] = Field(None, ge=1, le=31)
    next_payment_due_date: Optional[str] = None

    # Credit-specific
    credit_limit: Optional[Decimal] = None
    annual_fee: Optional[Decimal] = None
    annual_fee_month: Optional[int] = Field(None, ge=1, le=12)
    autopay_enabled: bool = False
    autopay_source_id: Optional[int] = None
    default_payment_source_id: Optional[int] = None

    # Loan-specific
    origination_date: Optional[str] = None
    origination_principal: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    loan_term: Optional[int] = None
    escrow_balance: Optional[Decimal] = None

    # Initial balance (required)
    balance: Decimal = Decimal("0")
    # Optional initial statement/available balance
    statement_balance: Optional[Decimal] = None
    available_balance: Optional[Decimal] = None

    # Payment source tag
    payment_source_tag: Optional[str] = None

    # Notes / personal debt
    notes: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_class: Optional[str] = Field(None, pattern="^(asset|liability)$")
    liability_type: Optional[str] = None
    asset_type: Optional[str] = None
    institution: Optional[str] = None
    last_four: Optional[str] = None
    responsibility: Optional[str] = None
    open_date: Optional[str] = None
    due_day: Optional[int] = Field(None, ge=1, le=31)
    next_payment_due_date: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    annual_fee: Optional[Decimal] = None
    annual_fee_month: Optional[int] = Field(None, ge=1, le=12)
    autopay_enabled: Optional[bool] = None
    autopay_source_id: Optional[int] = None
    default_payment_source_id: Optional[int] = None
    origination_date: Optional[str] = None
    origination_principal: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    loan_term: Optional[int] = None
    escrow_balance: Optional[Decimal] = None
    payment_source_tag: Optional[str] = None
    balance: Optional[Decimal] = None
    linked_account_id: Optional[str] = None
    linked_bank_name: Optional[str] = None


class AccountStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|closed|paid_off|frozen)$")


class AccountResponse(BaseModel):
    id: int
    name: str
    acct_type: str
    balance: Decimal
    is_asset: bool
    account_code: Optional[str] = None
    account_class: Optional[str] = None
    liability_type: Optional[str] = None
    asset_type: Optional[str] = None
    institution: Optional[str] = None
    last_four: Optional[str] = None
    responsibility: Optional[str] = None
    open_date: Optional[str] = None
    due_day: Optional[int] = None
    next_payment_due_date: Optional[str] = None
    last_payment_date: Optional[str] = None
    last_payment_amount: Optional[Decimal] = None
    last_statement_balance: Optional[Decimal] = None
    last_statement_issue_date: Optional[str] = None
    minimum_payment_amount: Optional[Decimal] = None
    credit_limit: Optional[Decimal] = None
    origination_date: Optional[str] = None
    origination_principal: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    loan_term: Optional[int] = None
    escrow_balance: Optional[Decimal] = None
    ytd_interest_paid: Optional[Decimal] = None
    ytd_principal_paid: Optional[Decimal] = None
    autopay_enabled: Optional[bool] = None
    autopay_source_id: Optional[int] = None
    default_payment_source_id: Optional[int] = None
    annual_fee: Optional[Decimal] = None
    annual_fee_month: Optional[int] = None
    payment_source_tag: Optional[str] = None
    last_verified_at: Optional[str] = None
    data_source: Optional[str] = None
    plaid_account_id: Optional[str] = None
    status: Optional[str] = None
    linked_account_id: Optional[str] = None
    linked_bank_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AccountListResponse(BaseModel):
    accounts: list[AccountResponse]
    total: int


# ── Balance Update ───────────────────────────────────────────────────────

class BalanceUpdateEntry(BaseModel):
    account_id: int
    current_balance: Decimal
    statement_balance: Optional[Decimal] = None
    minimum_payment: Optional[Decimal] = None
    data_source: str = "manual"


class BulkBalanceUpdateRequest(BaseModel):
    updates: list[BalanceUpdateEntry]


# ── Payment Source Tags ──────────────────────────────────────────────────

class PaymentSourceTagCreate(BaseModel):
    short_code: str
    account_id: int


class PaymentSourceTagResponse(BaseModel):
    short_code: str
    account_id: int
    created_at: str


# ── Billing Cycles ───────────────────────────────────────────────────────

class BillingCycleCreate(BaseModel):
    account_id: int
    cycle_label: str  # 'YYYY-MM'
    statement_balance: Decimal
    payment_due_date: str  # ISO date
    statement_open_date: Optional[str] = None
    statement_close_date: Optional[str] = None
    minimum_payment: Optional[Decimal] = None


class BillingCycleUpdate(BaseModel):
    statement_balance: Optional[Decimal] = None
    minimum_payment: Optional[Decimal] = None
    payment_due_date: Optional[str] = None
    statement_open_date: Optional[str] = None
    statement_close_date: Optional[str] = None
    status: Optional[str] = None


# ── Payment Plan ─────────────────────────────────────────────────────────

class PlanAssignment(BaseModel):
    liability_id: int
    source_id: int
    cycle_month: str  # 'YYYY-MM'
    planned_amount: Optional[Decimal] = None
    strategy: str = "statement"
    status: str = "planned"
    notes: Optional[str] = None


class PlanBulkRequest(BaseModel):
    assignments: list[PlanAssignment]


class PlanRollforwardRequest(BaseModel):
    from_month: str  # 'YYYY-MM'
    to_month: str    # 'YYYY-MM'


# ── Payments ─────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    payment_date: str  # ISO date
    amount: Decimal
    billing_cycle_id: Optional[int] = None
    payment_type: str = "manual"
    confirmation_ref: Optional[str] = None
    status: str = "pending"
    notes: Optional[str] = None
