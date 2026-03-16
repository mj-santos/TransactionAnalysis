"""Plaid API integration stubs — 501 Not Implemented.

These endpoints define the full contract for future Plaid/Finicity/MX integration.
Each returns HTTP 501 with a structured response documenting:
  - What the endpoint will do
  - Expected request/response schema
  - Plaid API fields that map to nw_accounts columns

When implementation begins, replace the 501 stubs with real logic.
The schema is already Plaid-aligned (field names match Plaid Liabilities API),
so integration requires zero field transformation.

Reference: https://plaid.com/docs/api/products/liabilities/
"""
from __future__ import annotations

from fastapi import HTTPException

from . import router


# ── Plaid field mapping documentation ─────────────────────────────────
# This mapping is embedded in the module so it serves as both
# documentation and a future implementation guide.

PLAID_FIELD_MAP = {
    # Plaid Liabilities response field → nw_accounts column
    "accounts[].account_id": "plaid_account_id",
    "accounts[].balances.current": "balance (via ap_balance_ledger.current_balance)",
    "accounts[].balances.available": "ap_balance_ledger.available_balance",
    "accounts[].name": "name",
    "accounts[].official_name": "name (fallback)",
    "accounts[].type": "account_class ('depository'→'asset', 'credit'/'loan'→'liability')",
    "accounts[].subtype": "liability_type / asset_type (mapped via _SUBTYPE_MAP)",
    "accounts[].mask": "last_four",
    # Liabilities-specific
    "liabilities.credit[].account_id": "plaid_account_id (join key)",
    "liabilities.credit[].last_statement_balance": "last_statement_balance",
    "liabilities.credit[].last_statement_issue_date": "last_statement_issue_date",
    "liabilities.credit[].minimum_payment_amount": "minimum_payment_amount",
    "liabilities.credit[].next_payment_due_date": "next_payment_due_date",
    "liabilities.credit[].last_payment_amount": "last_payment_amount",
    "liabilities.credit[].last_payment_date": "last_payment_date",
    "liabilities.credit[].aprs[].apr_percentage": "ap_apr_terms.apr_percentage",
    "liabilities.credit[].aprs[].apr_type": "ap_apr_terms.apr_type",
    "liabilities.credit[].aprs[].balance_subject_to_apr": "ap_apr_terms.balance_subject_to_apr",
    "liabilities.credit[].aprs[].interest_charge_amount": "ap_apr_terms.interest_charge_amount",
    # Mortgage-specific
    "liabilities.mortgage[].origination_date": "origination_date",
    "liabilities.mortgage[].origination_principal_amount": "origination_principal",
    "liabilities.mortgage[].interest_rate.percentage": "interest_rate",
    "liabilities.mortgage[].interest_rate.type": "(fixed/variable — stored as note)",
    "liabilities.mortgage[].loan_term": "loan_term",
    "liabilities.mortgage[].escrow_balance": "escrow_balance",
    "liabilities.mortgage[].ytd_interest_paid": "ytd_interest_paid",
    "liabilities.mortgage[].ytd_principal_paid": "ytd_principal_paid",
    "liabilities.mortgage[].next_monthly_payment": "minimum_payment_amount",
    # Student loan-specific
    "liabilities.student[].origination_date": "origination_date",
    "liabilities.student[].origination_principal_amount": "origination_principal",
    "liabilities.student[].interest_rate_percentage": "interest_rate",
    "liabilities.student[].loan_name": "name",
    "liabilities.student[].minimum_payment_amount": "minimum_payment_amount",
    "liabilities.student[].next_payment_due_date": "next_payment_due_date",
    "liabilities.student[].ytd_interest_paid": "ytd_interest_paid",
    "liabilities.student[].ytd_principal_paid": "ytd_principal_paid",
}

# Plaid subtype → Spendly type mapping
_SUBTYPE_MAP = {
    # Depository (assets)
    "checking": ("asset", "checking"),
    "savings": ("asset", "savings"),
    "money market": ("asset", "savings"),
    "cd": ("asset", "savings"),
    "hsa": ("asset", "savings"),
    "paypal": ("asset", "digital_wallet"),
    # Credit (liabilities)
    "credit card": ("liability", "credit_card"),
    # Loan (liabilities)
    "mortgage": ("liability", "mortgage"),
    "auto": ("liability", "auto_loan"),
    "student": ("liability", "student_loan"),
    "personal": ("liability", "personal_debt"),
    "home equity": ("liability", "mortgage"),
    "line of credit": ("liability", "credit_card"),
    # Investment (assets)
    "brokerage": ("asset", "investment"),
    "401k": ("asset", "investment"),
    "ira": ("asset", "investment"),
    "roth": ("asset", "investment"),
    "401a": ("asset", "investment"),
    "403b": ("asset", "investment"),
}

# Data source tags for audit trail
DATA_SOURCE_PLAID = "plaid"
DATA_SOURCE_FINICITY = "finicity"
DATA_SOURCE_MX = "mx"

# Refresh cadence options (for future settings UI)
REFRESH_CADENCES = {
    "manual": "User-initiated only",
    "daily": "Once per day (recommended)",
    "twice_daily": "Every 12 hours",
    "hourly": "Every hour (high API usage)",
}


def _not_implemented(feature: str, contract: dict) -> dict:
    """Standard 501 response with contract documentation."""
    raise HTTPException(
        status_code=501,
        detail={
            "error": "not_implemented",
            "feature": feature,
            "message": f"{feature} is not yet implemented. This endpoint documents the planned API contract.",
            "planned_contract": contract,
        },
    )


# ── Plaid Link Flow ──────────────────────────────────────────────────

@router.post("/connect/plaid/link-token",
             summary="Create Plaid Link token (501 stub)",
             status_code=501)
def route_create_link_token():
    """
    Creates a Plaid Link token to initiate the account connection flow.
    The frontend opens Plaid Link with this token, the user authenticates
    with their bank, and Plaid returns a public_token via callback.

    Plaid API: POST /link/token/create
    """
    _not_implemented("Plaid Link Token", {
        "method": "POST",
        "plaid_endpoint": "/link/token/create",
        "request": {
            "client_id": "string (from env PLAID_CLIENT_ID)",
            "secret": "string (from env PLAID_SECRET)",
            "user": {"client_user_id": "string (unique per user)"},
            "client_name": "Spendly",
            "products": ["liabilities", "transactions"],
            "country_codes": ["US"],
            "language": "en",
        },
        "response": {
            "link_token": "string (pass to Plaid Link frontend)",
            "expiration": "ISO datetime",
        },
        "implementation_notes": [
            "Requires PLAID_CLIENT_ID and PLAID_SECRET environment variables",
            "Link token expires in 4 hours",
            "Products array determines what data Plaid fetches",
            "Use 'sandbox' environment for development",
        ],
    })


@router.post("/connect/plaid/exchange",
             summary="Exchange public token for access token (501 stub)",
             status_code=501)
def route_exchange_token():
    """
    After user completes Plaid Link, exchange the public_token for a
    permanent access_token. Store the access_token securely — it's the
    key to all future data fetches for this institution.

    Plaid API: POST /item/public_token/exchange
    """
    _not_implemented("Plaid Token Exchange", {
        "method": "POST",
        "plaid_endpoint": "/item/public_token/exchange",
        "request": {
            "public_token": "string (from Plaid Link onSuccess callback)",
        },
        "response": {
            "access_token": "string (store encrypted in DB)",
            "item_id": "string (Plaid's ID for this institution connection)",
        },
        "storage": {
            "table": "ap_plaid_connections (NEW — to be created)",
            "columns": {
                "id": "BIGINT PRIMARY KEY",
                "item_id": "TEXT NOT NULL UNIQUE",
                "access_token": "TEXT NOT NULL (encrypted)",
                "institution_id": "TEXT",
                "institution_name": "TEXT",
                "status": "TEXT DEFAULT 'active'",
                "consent_expiration": "TEXT (ISO date)",
                "last_refresh_at": "TEXT",
                "created_at": "TEXT",
            },
        },
        "implementation_notes": [
            "Access token MUST be encrypted at rest (use Fernet or similar)",
            "Never log or expose access tokens in API responses",
            "One item_id per institution — covers all accounts at that bank",
            "Token is permanent until user revokes or consent expires",
        ],
    })


@router.post("/connect/plaid/callback",
             summary="Handle Plaid Link redirect/webhook (501 stub)",
             status_code=501)
def route_plaid_callback():
    """
    Webhook endpoint for Plaid to notify of events:
    - INITIAL_UPDATE: first batch of transactions ready
    - HISTORICAL_UPDATE: full history loaded
    - DEFAULT_UPDATE: new transactions available
    - TRANSACTIONS_REMOVED: transactions deleted at source

    Plaid Webhooks: https://plaid.com/docs/api/webhooks/
    """
    _not_implemented("Plaid Webhook Callback", {
        "method": "POST",
        "webhook_types": {
            "TRANSACTIONS": [
                "INITIAL_UPDATE",
                "HISTORICAL_UPDATE",
                "DEFAULT_UPDATE",
                "TRANSACTIONS_REMOVED",
            ],
            "LIABILITIES": [
                "DEFAULT_UPDATE",
            ],
            "ITEM": [
                "ERROR",
                "PENDING_EXPIRATION",
                "USER_PERMISSION_REVOKED",
            ],
        },
        "verification": "Verify webhook using Plaid webhook verification key",
        "implementation_notes": [
            "Register webhook URL in Plaid dashboard",
            "Verify webhook signatures to prevent spoofing",
            "Queue webhook processing — don't block the response",
            "Handle ITEM.ERROR by prompting user to re-authenticate",
        ],
    })


# ── Account Refresh ──────────────────────────────────────────────────

@router.post("/connect/refresh",
             summary="Fetch latest balances from connected provider (501 stub)",
             status_code=501)
def route_refresh_balances():
    """
    Pull latest balance data from Plaid for all connected accounts
    (or a specific account). Creates ap_balance_ledger entries with
    data_source='plaid' and updates nw_accounts.

    Plaid API: POST /accounts/balance/get + POST /liabilities/get
    """
    _not_implemented("Balance Refresh", {
        "method": "POST",
        "request": {
            "account_id": "int | null (null = refresh all connected accounts)",
            "force": "bool (bypass cache, default false)",
        },
        "plaid_calls": [
            {
                "endpoint": "/accounts/balance/get",
                "purpose": "Fetch current + available balances for all accounts",
                "maps_to": "ap_balance_ledger (current_balance, available_balance)",
            },
            {
                "endpoint": "/liabilities/get",
                "purpose": "Fetch credit card, mortgage, student loan details",
                "maps_to": "nw_accounts (statement fields) + ap_apr_terms + ap_billing_cycles",
            },
        ],
        "response": {
            "refreshed": "int (number of accounts updated)",
            "accounts": [
                {
                    "id": "int (nw_accounts.id)",
                    "name": "string",
                    "old_balance": "number",
                    "new_balance": "number",
                    "change": "number",
                },
            ],
            "snapshot_generated": "bool",
            "errors": ["list of per-account errors if any"],
        },
        "processing_steps": [
            "1. Look up access_token from ap_plaid_connections for the account's plaid_account_id",
            "2. Call /accounts/balance/get with access_token",
            "3. For each Plaid account, find matching nw_accounts row by plaid_account_id",
            "4. Insert ap_balance_ledger row with data_source='plaid'",
            "5. Update nw_accounts.balance, last_verified_at, data_source",
            "6. For liabilities: call /liabilities/get, update statement fields",
            "7. Auto-create ap_billing_cycles from statement data if new cycle detected",
            "8. Generate nw_snapshots entry",
            "9. If auto_calculate setting is on, trigger payment plan recalculation",
        ],
        "field_mapping": PLAID_FIELD_MAP,
    })


@router.get("/connect/refresh/status",
            summary="Poll refresh job status (501 stub)",
            status_code=501)
def route_refresh_status():
    """
    Check the status of an in-progress balance refresh.
    Refresh may take 5-30 seconds depending on the institution.
    """
    _not_implemented("Refresh Status", {
        "method": "GET",
        "request": {
            "job_id": "string (from POST /connect/refresh response)",
        },
        "response": {
            "status": "pending | in_progress | completed | failed",
            "progress": "int (0-100)",
            "accounts_refreshed": "int",
            "accounts_total": "int",
            "errors": [],
            "completed_at": "ISO datetime | null",
        },
    })


# ── Connection Management ────────────────────────────────────────────

@router.get("/connect/institutions",
            summary="List connected institutions (501 stub)",
            status_code=501)
def route_list_institutions():
    """
    List all institutions the user has connected via Plaid Link.
    Each institution may provide multiple accounts.
    """
    _not_implemented("Connected Institutions", {
        "method": "GET",
        "response": {
            "institutions": [
                {
                    "item_id": "string",
                    "institution_name": "string",
                    "institution_id": "string",
                    "status": "active | error | pending_reauth",
                    "accounts_count": "int",
                    "last_refresh": "ISO datetime | null",
                    "consent_expires": "ISO date | null",
                    "error_message": "string | null",
                },
            ],
        },
    })


@router.delete("/connect/institutions/{item_id}",
               summary="Disconnect an institution (501 stub)",
               status_code=501)
def route_disconnect_institution(item_id: str):
    """
    Revoke Plaid access for an institution. This removes the access_token
    and unlinks all accounts from that institution. Account data in
    nw_accounts is preserved but data_source reverts to 'manual'.

    Plaid API: POST /item/remove
    """
    _not_implemented("Disconnect Institution", {
        "method": "DELETE",
        "plaid_endpoint": "/item/remove",
        "request": {
            "item_id": "string (path parameter)",
        },
        "side_effects": [
            "Delete access_token from ap_plaid_connections",
            "Set nw_accounts.plaid_account_id = NULL for affected accounts",
            "Set nw_accounts.data_source = 'manual' for affected accounts",
            "Preserve all balance history and payment records",
        ],
    })


# ── Auto-Verify Payments ─────────────────────────────────────────────

@router.post("/connect/auto-verify",
             summary="Auto-verify all pending payments against bank data (501 stub)",
             status_code=501)
def route_auto_verify():
    """
    Automatically cross-reference all unverified ap_payments records
    against fresh transaction data from Plaid. This is the automated
    version of the manual verify_payment() in cross_module.py.

    Only works for accounts connected via Plaid (data_source='plaid').
    """
    _not_implemented("Auto-Verify Payments", {
        "method": "POST",
        "request": {
            "cycle_month": "string | null ('YYYY-MM', null = current month)",
            "account_id": "int | null (null = all connected accounts)",
        },
        "response": {
            "verified": "int (newly verified payments)",
            "already_verified": "int",
            "unmatched": "int (no bank transaction found)",
            "details": [
                {
                    "payment_id": "int",
                    "status": "verified | unmatched",
                    "matched_fingerprint": "string | null",
                    "matched_date": "ISO date | null",
                },
            ],
        },
        "processing_steps": [
            "1. Fetch recent transactions from Plaid for connected accounts",
            "2. For each unverified ap_payments row:",
            "   a. Find from_account's linked Plaid account",
            "   b. Search Plaid transactions: amount ± $0.01, date ± 3 days",
            "   c. If match found: set verified=TRUE, store fingerprint",
            "3. Return summary of verification results",
        ],
        "prerequisites": [
            "Account must have plaid_account_id set",
            "Recent balance refresh must have occurred (< 24 hours)",
        ],
    })


# ── Settings ─────────────────────────────────────────────────────────

@router.get("/connect/settings",
            summary="Get API integration settings (501 stub)",
            status_code=501)
def route_get_settings():
    """
    Retrieve user's API integration preferences.
    """
    _not_implemented("API Settings", {
        "method": "GET",
        "response": {
            "auto_refresh": "bool (auto-refresh on schedule)",
            "refresh_cadence": "string (manual | daily | twice_daily | hourly)",
            "auto_calculate": "bool (auto-recalculate payment plans after refresh)",
            "auto_verify": "bool (auto-verify payments after refresh)",
            "auto_snapshot": "bool (auto-generate NW snapshot after refresh)",
            "notification_on_refresh": "bool (toast notification after auto-refresh)",
            "notification_on_error": "bool (alert on connection errors)",
        },
        "storage": "data/ui_settings.json → plaid_settings key",
    })


@router.put("/connect/settings",
            summary="Update API integration settings (501 stub)",
            status_code=501)
def route_update_settings():
    """
    Update user's API integration preferences.
    """
    _not_implemented("API Settings Update", {
        "method": "PUT",
        "request": {
            "auto_refresh": "bool",
            "refresh_cadence": "string",
            "auto_calculate": "bool",
            "auto_verify": "bool",
            "auto_snapshot": "bool",
        },
    })


# ── Diagnostic / Field Mapping ────────────────────────────────────────

@router.get("/connect/field-map",
            summary="Return Plaid → Spendly field mapping documentation")
def route_field_map():
    """
    Returns the complete field mapping between Plaid API responses
    and Spendly's nw_accounts / ap_* tables. This is a reference
    endpoint for developers implementing the integration.
    """
    return {
        "plaid_to_spendly": PLAID_FIELD_MAP,
        "subtype_map": _SUBTYPE_MAP,
        "data_sources": {
            "plaid": "Plaid API (primary)",
            "finicity": "Finicity API (alternative)",
            "mx": "MX API (alternative)",
            "manual": "User-entered data",
            "csv_import": "Imported from CSV/XLSX file",
        },
        "refresh_cadences": REFRESH_CADENCES,
        "notes": [
            "All nw_accounts columns use Plaid-aligned field names for zero-transform ingestion",
            "data_source field on every record provides clean audit trail",
            "plaid_account_id on nw_accounts is the stable link for refresh cycles",
            "Balance updates always create new ap_balance_ledger rows (immutable history)",
            "Billing cycles auto-created when Plaid returns new statement data",
        ],
    }
