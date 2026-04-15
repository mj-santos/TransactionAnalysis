"""
DuckDB connection management and schema bootstrap.

All DDL matches database_design.txt exactly.
"""
from __future__ import annotations

import multiprocessing
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE SEQUENCE IF NOT EXISTS seq_merchant_rules_id;

CREATE TABLE IF NOT EXISTS merchant_rules (
  id         BIGINT DEFAULT nextval('seq_merchant_rules_id') PRIMARY KEY,
  pattern    TEXT    NOT NULL,
  match_type TEXT    NOT NULL DEFAULT 'contains',
  merchant   TEXT    NOT NULL,
  priority   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    NOT NULL,
  updated_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_category_map (
  merchant   TEXT    PRIMARY KEY,
  category   TEXT    NOT NULL,
  source     TEXT    NOT NULL DEFAULT 'user',
  updated_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS normalization_jobs (
  job_id      TEXT    PRIMARY KEY,
  status      TEXT    NOT NULL DEFAULT 'pending',
  rows_total  BIGINT,
  rows_done   BIGINT DEFAULT 0,
  error       TEXT,
  started_at  TEXT,
  finished_at TEXT,
  created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_files (
  file_hash         TEXT PRIMARY KEY,
  original_path     TEXT,
  ingested_path     TEXT,
  ingested_at       TIMESTAMP,
  file_size_bytes   BIGINT,
  delimiter         TEXT,
  encoding          TEXT,
  header_json       TEXT,
  profile_path      TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  run_id            TEXT PRIMARY KEY,
  started_at        TIMESTAMP,
  finished_at       TIMESTAMP,
  status            TEXT,
  statement_type    TEXT,
  run_label         TEXT,
  files_count       INTEGER,
  rows_in           BIGINT,
  rows_staged       BIGINT,
  rows_normalized   BIGINT,
  rows_loaded       BIGINT,
  errors_count      INTEGER,
  notes             TEXT,
  imported_file     TEXT
);

CREATE TABLE IF NOT EXISTS transactions_stage (
  run_id                TEXT,
  file_hash             TEXT,
  source_file           TEXT,
  source_row            INTEGER,
  bank_name             TEXT,
  account_name          TEXT,
  account_id            TEXT,
  transaction_date_raw  TEXT,
  posted_date_raw       TEXT,
  description_raw       TEXT,
  amount_raw            TEXT,
  debit_raw             TEXT,
  credit_raw            TEXT,
  money_in_raw          TEXT,
  money_out_raw         TEXT,
  dc_flag_raw           TEXT,
  currency_raw          TEXT,
  extra_json            TEXT,
  amount_debit_raw      TEXT,
  amount_credit_raw     TEXT
);

CREATE TABLE IF NOT EXISTS transactions_norm (
  transaction_date      DATE        NOT NULL,
  posted_date           DATE,
  description           TEXT        NOT NULL,
  merchant              TEXT,
  category              TEXT,
  amount                DECIMAL(18,2) NOT NULL,
  currency              TEXT        DEFAULT 'USD',
  bank_name             TEXT        NOT NULL,
  account_name          TEXT        NOT NULL,
  account_id            TEXT        NOT NULL,
  source_file           TEXT        NOT NULL,
  source_row            INTEGER     NOT NULL,
  file_hash             TEXT        NOT NULL,
  transaction_fingerprint TEXT      NOT NULL,
  ingested_at           TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
  statement_type        TEXT,
  run_id                TEXT,
  -- Credit-card classification: spending / payment / adjustment / NULL (bank rows)
  transaction_subtype   TEXT,
  -- Unsigned resolved amount (always >= 0), direction encoded in transaction_subtype
  resolved_amount       DECIMAL(18,2)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_fingerprint
  ON transactions_norm(transaction_fingerprint);

CREATE SEQUENCE IF NOT EXISTS seq_duplicate_candidates_id;
CREATE TABLE IF NOT EXISTS duplicate_candidates (
  id                    BIGINT DEFAULT nextval('seq_duplicate_candidates_id') PRIMARY KEY,
  fingerprint_a         TEXT NOT NULL,
  fingerprint_b         TEXT NOT NULL,
  similarity_score      DECIMAL(3,2),
  reason                TEXT,
  status                TEXT DEFAULT 'pending',
  detected_at           TEXT NOT NULL,
  resolved_at           TEXT
);
"""

# ---------------------------------------------------------------------------
# Migrations — add new columns to existing databases (idempotent)
# ---------------------------------------------------------------------------

_MIGRATIONS = [
    # ── Column additions ────────────────────────────────────────────────────
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS statement_type TEXT",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS run_label TEXT",
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS statement_type TEXT",
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS run_id TEXT",
    "ALTER TABLE transactions_stage ADD COLUMN IF NOT EXISTS amount_debit_raw TEXT",
    "ALTER TABLE transactions_stage ADD COLUMN IF NOT EXISTS amount_credit_raw TEXT",

    # ── Backfill: NULL statement_type → 'bank' ──────────────────────────────
    "UPDATE transactions_norm SET statement_type = 'bank' WHERE statement_type IS NULL",
    # ── Add credit-card subtype columns ─────────────────────────────────────
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS transaction_subtype TEXT",
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS resolved_amount DECIMAL(18,2)",

    # ── Add imported_file column to runs ────────────────────────────────────
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS imported_file TEXT",
    # ── Add merchant normalization tables (idempotent via CREATE IF NOT EXISTS) ──
    "CREATE SEQUENCE IF NOT EXISTS seq_merchant_rules_id",
    """
    CREATE TABLE IF NOT EXISTS merchant_rules (
      id         BIGINT DEFAULT nextval('seq_merchant_rules_id') PRIMARY KEY,
      pattern    TEXT    NOT NULL,
      match_type TEXT    NOT NULL DEFAULT 'contains',
      merchant   TEXT    NOT NULL,
      priority   INTEGER NOT NULL DEFAULT 0,
      created_at TEXT    NOT NULL,
      updated_at TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_category_map (
      merchant   TEXT    PRIMARY KEY,
      category   TEXT    NOT NULL,
      source     TEXT    NOT NULL DEFAULT 'user',
      updated_at TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS normalization_jobs (
      job_id      TEXT    PRIMARY KEY,
      status      TEXT    NOT NULL DEFAULT 'pending',
      rows_total  BIGINT,
      rows_done   BIGINT DEFAULT 0,
      error       TEXT,
      started_at  TEXT,
      finished_at TEXT,
      created_at  TEXT    NOT NULL
    )
    """,
    # ── Add compound condition columns to merchant_rules ────────────────────
    "ALTER TABLE merchant_rules ADD COLUMN IF NOT EXISTS conditions TEXT",
    "ALTER TABLE merchant_rules ADD COLUMN IF NOT EXISTS logic TEXT DEFAULT 'AND'",

    # ── Backfill: run_id via transactions_stage join ─────────────────────────
    # Link each transaction back to the run that created it.  Rows where
    # transactions_stage has already been deleted (e.g., after a purge) will
    # retain run_id = NULL and remain accessible via "Display All" in the UI.
    """
    UPDATE transactions_norm
    SET run_id = (
        SELECT ts.run_id
        FROM transactions_stage ts
        WHERE ts.file_hash = transactions_norm.file_hash
        LIMIT 1
    )
    WHERE run_id IS NULL
    """,

    # ── Category normalization ───────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_category_rules_id",
    """
CREATE TABLE IF NOT EXISTS category_rules (
  id           BIGINT DEFAULT nextval('seq_category_rules_id') PRIMARY KEY,
  raw_category TEXT    NOT NULL UNIQUE,
  category     TEXT    NOT NULL,
  parent       TEXT    NOT NULL,
  created_at   TEXT    NOT NULL,
  updated_at   TEXT    NOT NULL
)
""",
    "ALTER TABLE category_rules ADD COLUMN IF NOT EXISTS conditions TEXT",
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS category_normalized TEXT",
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS category_parent TEXT",

    # ── Budget goals ─────────────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_budget_goals_id",
    """
CREATE TABLE IF NOT EXISTS budget_goals (
  id             BIGINT DEFAULT nextval('seq_budget_goals_id') PRIMARY KEY,
  parent         TEXT    NOT NULL,
  category       TEXT,
  monthly_amount DECIMAL(18,2) NOT NULL,
  created_at     TEXT    NOT NULL,
  updated_at     TEXT    NOT NULL,
  UNIQUE(parent, category)
)
""",

    # ── Transaction review tracking ──────────────────────────────────────────
    # NOTE: DO NOT use "ADD COLUMN IF NOT EXISTS ... DEFAULT <value>" for
    # BOOLEAN columns — DuckDB >=1.5 re-applies the DEFAULT to all existing
    # rows even when the column already exists (value-clobbering bug).
    # Dropping "IF NOT EXISTS" makes DuckDB raise on re-run, caught by the
    # blanket except below, which preserves existing data.
    "ALTER TABLE transactions_norm ADD COLUMN unreviewed BOOLEAN DEFAULT TRUE",

    # ── Schema version tracking (for backup compatibility) ────────────────
    "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)",
    # Seed with version 1 if table is empty (first migration)
    "INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version)",

    # ── Recurring transaction overrides ──────────────────────────────────
    # Stores user manual overrides (mark/unmark) for recurring detection.
    # merchant_key is the normalized merchant name used as the grouping key.
    "CREATE SEQUENCE IF NOT EXISTS seq_recurring_overrides_id",
    """
CREATE TABLE IF NOT EXISTS recurring_overrides (
  id           BIGINT DEFAULT nextval('seq_recurring_overrides_id') PRIMARY KEY,
  merchant_key TEXT   NOT NULL UNIQUE,
  is_recurring BOOLEAN NOT NULL,
  created_at   TEXT   NOT NULL,
  updated_at   TEXT   NOT NULL
)
""",

    # ── Tags ───────────────────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_tags_id",
    """
CREATE TABLE IF NOT EXISTS tags (
  id         BIGINT DEFAULT nextval('seq_tags_id') PRIMARY KEY,
  name       TEXT   NOT NULL UNIQUE,
  color      TEXT   NOT NULL DEFAULT '#3b82f6',
  created_at TEXT   NOT NULL,
  updated_at TEXT   NOT NULL
)
""",
    """
CREATE TABLE IF NOT EXISTS transaction_tags (
  transaction_fingerprint TEXT NOT NULL,
  tag_id                  BIGINT NOT NULL,
  created_at              TEXT NOT NULL,
  UNIQUE(transaction_fingerprint, tag_id)
)
""",

    # ── Savings Goals ──────────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_savings_goals_id",
    """
CREATE TABLE IF NOT EXISTS savings_goals (
  id              BIGINT DEFAULT nextval('seq_savings_goals_id') PRIMARY KEY,
  name            TEXT    NOT NULL,
  target_amount   DECIMAL(18,2) NOT NULL,
  current_amount  DECIMAL(18,2) NOT NULL DEFAULT 0,
  target_date     TEXT,
  linked_account  TEXT,
  created_at      TEXT    NOT NULL,
  updated_at      TEXT    NOT NULL
)
""",

    # ── Monthly Summaries ─────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_monthly_summaries_id",
    """
CREATE TABLE IF NOT EXISTS monthly_summaries (
  id           BIGINT DEFAULT nextval('seq_monthly_summaries_id') PRIMARY KEY,
  year         INTEGER NOT NULL,
  month        INTEGER NOT NULL,
  summary_json TEXT    NOT NULL,
  narrative    TEXT    NOT NULL,
  created_at   TEXT    NOT NULL,
  UNIQUE(year, month)
)
""",

    # ── Net Worth Accounts ─────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_nw_accounts_id",
    """
CREATE TABLE IF NOT EXISTS nw_accounts (
  id         BIGINT DEFAULT nextval('seq_nw_accounts_id') PRIMARY KEY,
  name       TEXT    NOT NULL,
  acct_type  TEXT    NOT NULL,
  balance    DECIMAL(18,2) NOT NULL DEFAULT 0,
  is_asset   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT    NOT NULL,
  updated_at TEXT    NOT NULL
)
""",

    # ── Net Worth Snapshots ────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_nw_snapshots_id",
    """
CREATE TABLE IF NOT EXISTS nw_snapshots (
  id            BIGINT DEFAULT nextval('seq_nw_snapshots_id') PRIMARY KEY,
  snapshot_date TEXT    NOT NULL,
  total_assets  DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_liab    DECIMAL(18,2) NOT NULL DEFAULT 0,
  net_worth     DECIMAL(18,2) NOT NULL DEFAULT 0,
  detail_json   TEXT    NOT NULL,
  created_at    TEXT    NOT NULL
)
""",

    # ── Annual Reports ─────────────────────────────────────────────────────
    "CREATE SEQUENCE IF NOT EXISTS seq_annual_reports_id",
    """
CREATE TABLE IF NOT EXISTS annual_reports (
  id           BIGINT DEFAULT nextval('seq_annual_reports_id') PRIMARY KEY,
  year         INTEGER NOT NULL UNIQUE,
  report_json  TEXT    NOT NULL,
  narrative    TEXT    NOT NULL,
  created_at   TEXT    NOT NULL,
  updated_at   TEXT    NOT NULL
)
""",

    # ── Transaction Notes ─────────────────────────────────────────────────────
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS notes TEXT",

    # ── Split Transactions ────────────────────────────────────────────────────
    "ALTER TABLE transactions_norm ADD COLUMN is_split BOOLEAN DEFAULT FALSE",
    "ALTER TABLE transactions_norm ADD COLUMN IF NOT EXISTS split_parent_fingerprint TEXT",

    # ── Category Override flag ─────────────────────────────────────────────────
    "ALTER TABLE transactions_norm ADD COLUMN category_override BOOLEAN DEFAULT FALSE",

    # ── Excluded flag (hide transaction from totals/queries) ──────────────────
    "ALTER TABLE transactions_norm ADD COLUMN excluded BOOLEAN DEFAULT FALSE",

    # ── Recurring overrides: extended fields for annual fee suggestions ──────
    "ALTER TABLE recurring_overrides ADD COLUMN label TEXT",
    "ALTER TABLE recurring_overrides ADD COLUMN amount DECIMAL(18,2)",
    "ALTER TABLE recurring_overrides ADD COLUMN frequency TEXT",

    # ── Recurring overrides: pause & date tracking ─────────────────────────
    "ALTER TABLE recurring_overrides ADD COLUMN paused BOOLEAN DEFAULT FALSE",
    "ALTER TABLE recurring_overrides ADD COLUMN last_date TEXT",

    # ── Recurring overrides: user-editable next_estimated ────────────────
    "ALTER TABLE recurring_overrides ADD COLUMN next_estimated TEXT",

    # ── Recurring overrides: reimbursement tracking ───────────────────────
    "ALTER TABLE recurring_overrides ADD COLUMN reimbursement_type TEXT",
    "ALTER TABLE recurring_overrides ADD COLUMN reimbursed_amount DECIMAL(18,2)",

    # ── Recurring suggestion dismissals ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS recurring_dismissals (
        suggestion_id TEXT PRIMARY KEY,
        dismissed_at  TEXT NOT NULL
    )""",

    # ── Category suggestion dismissals ────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS category_dismissals (
        suggestion_key TEXT PRIMARY KEY,
        dismissed_at   TEXT NOT NULL
    )""",

    # ── Rule suggestion dismissals ────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS rule_dismissals (
        suggestion_key TEXT PRIMARY KEY,
        dismissed_at   TEXT NOT NULL
    )""",

    # ── Custom category taxonomy entries ──────────────────────────────────
    # Stores user-created subcategory/parent pairs that appear in dropdowns
    # and taxonomy views but do not map a raw bank category string.
    # Isolated from category_rules to avoid polluting the rule engine.
    """CREATE TABLE IF NOT EXISTS custom_categories (
        subcategory TEXT NOT NULL,
        parent      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        UNIQUE(subcategory, parent)
    )""",

    # ── Recurring payment log (mark-as-paid on upcoming bills widget) ───────
    "CREATE SEQUENCE IF NOT EXISTS seq_recurring_payment_log_id",
    """CREATE TABLE IF NOT EXISTS recurring_payment_log (
        id               BIGINT DEFAULT nextval('seq_recurring_payment_log_id') PRIMARY KEY,
        merchant         TEXT   NOT NULL,
        occurrence_date  TEXT   NOT NULL,
        amount_due       DECIMAL(18,2),
        paid_amount      DECIMAL(18,2) NOT NULL,
        payment_type     TEXT   NOT NULL DEFAULT 'full',
        record_in_accounts BOOLEAN DEFAULT FALSE,
        notes            TEXT,
        created_at       TEXT   NOT NULL,
        UNIQUE(merchant, occurrence_date)
    )""",

    # ── Saved reports (user-defined reusable filter+groupby presets) ──────
    "CREATE SEQUENCE IF NOT EXISTS seq_saved_reports_id",
    """CREATE TABLE IF NOT EXISTS saved_reports (
        id          BIGINT DEFAULT nextval('seq_saved_reports_id') PRIMARY KEY,
        name        TEXT NOT NULL,
        description TEXT,
        stmt_type   TEXT NOT NULL DEFAULT 'both',
        filters_json TEXT NOT NULL DEFAULT '[]',
        group_by_json TEXT NOT NULL DEFAULT '[]',
        bucket      TEXT,
        date_from   TEXT,
        date_to     TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
]

# ── Accounts & Liabilities module migrations ─────────────────────────────
from finance_etl.accounts.db_migrations import ACCOUNT_MIGRATIONS  # noqa: E402
_MIGRATIONS.extend(ACCOUNT_MIGRATIONS)
# ---------------------------------------------------------------------------

# Tracked migrations — each has a stable integer ID and is run only once.
# IDs must be unique and never reused/renumbered.
_TRACKED_MIGRATIONS: list[tuple[int, str]] = [
    # 1: Backfill unreviewed NULL → TRUE (safe after unreviewed column added)
    (1, "UPDATE transactions_norm SET unreviewed = TRUE WHERE unreviewed IS NULL"),
    # 2-4: Composite indexes for common query patterns
    (2, "CREATE INDEX IF NOT EXISTS idx_tx_type_date ON transactions_norm (statement_type, transaction_date DESC)"),
    (3, "CREATE INDEX IF NOT EXISTS idx_tx_unreviewed_type ON transactions_norm (unreviewed, statement_type)"),
    (4, "CREATE INDEX IF NOT EXISTS idx_tx_merchant_date ON transactions_norm (merchant, transaction_date)"),
]

def get_connection(db_path: str | Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open (or create) the DuckDB database and return a connection."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(db_path), read_only=read_only)

    if not read_only:
        _apply_pragmas(conn)
        _bootstrap_schema(conn)

    return conn


def _apply_pragmas(conn) -> None:
    threads = multiprocessing.cpu_count()
    conn.execute(f"PRAGMA threads = {threads};")
    conn.execute("PRAGMA enable_object_cache = true;")


def _bootstrap_schema(conn) -> None:
    """Apply DDL then run migrations idempotently."""
    for statement in _DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)

    # Ensure migration tracking table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id INTEGER PRIMARY KEY,
            applied_at   TEXT NOT NULL
        )
    """)

    applied = {row[0] for row in conn.execute("SELECT migration_id FROM schema_migrations").fetchall()}

    # Migrations for databases created before these columns existed
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    # Tracked (expensive) migrations — skipped once applied
    import datetime as _dt
    for mid, sql in _TRACKED_MIGRATIONS:
        if mid in applied:
            continue
        try:
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, ?)",
                [mid, _dt.datetime.utcnow().isoformat()],
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
