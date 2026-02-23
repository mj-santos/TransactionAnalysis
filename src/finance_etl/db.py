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
  extra_json            TEXT
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
  ingested_at           TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_fingerprint
  ON transactions_norm(transaction_fingerprint);
"""


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
    """Apply DDL idempotently (CREATE IF NOT EXISTS)."""
    for statement in _DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
