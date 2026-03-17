"""
Database migrations for the Accounts & Liabilities module.

These SQL strings are appended to db.py._MIGRATIONS.
Exported here for independent testing.
"""

ACCOUNT_MIGRATIONS = [
    # ── nw_accounts extensions (CoA + Plaid-aligned fields) ───────────────
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS account_code TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS account_class TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS liability_type TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS asset_type TEXT",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS institution TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS last_four TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS responsibility TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS open_date TEXT",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS next_payment_due_date TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS last_payment_date TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS last_payment_amount DECIMAL(18,2)",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS last_statement_balance DECIMAL(18,2)",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS last_statement_issue_date TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS minimum_payment_amount DECIMAL(18,2)",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS credit_limit DECIMAL(18,2)",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS origination_date TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS origination_principal DECIMAL(18,2)",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS interest_rate DECIMAL(8,4)",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS loan_term INTEGER",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS escrow_balance DECIMAL(18,2)",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS ytd_interest_paid DECIMAL(18,2)",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS ytd_principal_paid DECIMAL(18,2)",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS autopay_enabled BOOLEAN DEFAULT FALSE",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS autopay_source_id BIGINT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS default_payment_source_id BIGINT",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS annual_fee DECIMAL(10,2) DEFAULT 0",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS annual_fee_month INTEGER",

    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS payment_source_tag TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS last_verified_at TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS data_source TEXT DEFAULT 'manual'",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS plaid_account_id TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS due_day INTEGER",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS linked_account_id TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS linked_bank_name TEXT",
    "ALTER TABLE nw_accounts ADD COLUMN IF NOT EXISTS monthly_payment DECIMAL(18,2)",

    # ── ap_balance_ledger ─────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_ap_balance_ledger_id",
    """CREATE TABLE IF NOT EXISTS ap_balance_ledger (
    id                    BIGINT DEFAULT nextval('seq_ap_balance_ledger_id') PRIMARY KEY,
    account_id            BIGINT NOT NULL,
    observed_at           TEXT NOT NULL,
    effective_date        TEXT NOT NULL,
    current_balance       DECIMAL(18,2) NOT NULL,
    statement_balance     DECIMAL(18,2),
    minimum_payment       DECIMAL(18,2),
    credit_limit          DECIMAL(18,2),
    principal_balance     DECIMAL(18,2),
    escrow_balance        DECIMAL(18,2),
    interest_rate         DECIMAL(8,4),
    available_balance     DECIMAL(18,2),
    data_source           TEXT DEFAULT 'manual',
    notes                 TEXT,
    created_at            TEXT NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS idx_bl_account_date ON ap_balance_ledger(account_id, effective_date)",

    # ── ap_billing_cycles ─────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_ap_billing_cycles_id",
    """CREATE TABLE IF NOT EXISTS ap_billing_cycles (
    id                    BIGINT DEFAULT nextval('seq_ap_billing_cycles_id') PRIMARY KEY,
    account_id            BIGINT NOT NULL,
    cycle_label           TEXT NOT NULL,
    statement_open_date   TEXT,
    statement_close_date  TEXT,
    statement_balance     DECIMAL(18,2) NOT NULL,
    minimum_payment       DECIMAL(18,2),
    payment_due_date      TEXT NOT NULL,
    status                TEXT DEFAULT 'open',
    total_paid            DECIMAL(18,2) DEFAULT 0,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(account_id, cycle_label)
)""",

    # ── ap_payments ───────────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_ap_payments_id",
    """CREATE TABLE IF NOT EXISTS ap_payments (
    id                    BIGINT DEFAULT nextval('seq_ap_payments_id') PRIMARY KEY,
    from_account_id       BIGINT NOT NULL,
    to_account_id         BIGINT NOT NULL,
    billing_cycle_id      BIGINT,
    payment_date          TEXT NOT NULL,
    amount                DECIMAL(18,2) NOT NULL,
    payment_type          TEXT DEFAULT 'manual',
    confirmation_ref      TEXT,
    status                TEXT DEFAULT 'pending',
    verified              BOOLEAN DEFAULT FALSE,
    verified_fingerprint  TEXT,
    data_source           TEXT DEFAULT 'manual',
    notes                 TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
)""",

    # ── ap_payment_plan ───────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_ap_payment_plan_id",
    """CREATE TABLE IF NOT EXISTS ap_payment_plan (
    id                    BIGINT DEFAULT nextval('seq_ap_payment_plan_id') PRIMARY KEY,
    liability_id          BIGINT NOT NULL,
    source_id             BIGINT NOT NULL,
    cycle_month           TEXT NOT NULL,
    planned_amount        DECIMAL(18,2),
    strategy              TEXT DEFAULT 'statement',
    status                TEXT DEFAULT 'planned',
    notes                 TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE(liability_id, cycle_month)
)""",

    # ── ap_payment_source_tags ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS ap_payment_source_tags (
    short_code            TEXT PRIMARY KEY,
    account_id            BIGINT NOT NULL,
    created_at            TEXT NOT NULL
)""",

    # ── ap_card_benefits ──────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_ap_card_benefits_id",
    """CREATE TABLE IF NOT EXISTS ap_card_benefits (
    id                    BIGINT DEFAULT nextval('seq_ap_card_benefits_id') PRIMARY KEY,
    account_id            BIGINT NOT NULL,
    benefit_name          TEXT NOT NULL,
    benefit_type          TEXT NOT NULL,
    amount                DECIMAL(10,2),
    frequency             TEXT,
    provider              TEXT,
    redemption_notes      TEXT,
    auto_applied          BOOLEAN DEFAULT FALSE,
    created_at            TEXT NOT NULL
)""",

    # ── ap_apr_terms ──────────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_ap_apr_terms_id",
    """CREATE TABLE IF NOT EXISTS ap_apr_terms (
    id                    BIGINT DEFAULT nextval('seq_ap_apr_terms_id') PRIMARY KEY,
    account_id            BIGINT NOT NULL,
    apr_type              TEXT NOT NULL,
    apr_percentage        DECIMAL(8,4) NOT NULL,
    balance_subject_to_apr DECIMAL(18,2),
    interest_charge_amount DECIMAL(18,2),
    effective_date        TEXT,
    expiration_date       TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
)""",
]
