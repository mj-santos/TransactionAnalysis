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
  notes             TEXT
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
]


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

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
    # Migrations for databases created before these columns existed
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except Exception:
            pass  # column already exists — safe to ignore
