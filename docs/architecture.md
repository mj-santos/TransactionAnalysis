# Architecture — finance_etl

## Overview

`finance_etl` is a single-machine, fully local ETL pipeline. There is no network dependency, no cloud service, and no LLM. All data lives on disk; DuckDB is the analytical engine.

---

## Data Flow

```
  CSV Files (immutable originals)
       │
       ▼
  ┌──────────────────────────────────────────┐
  │  Stage 2 — Ingest / Register             │
  │  • SHA-256 file hash                     │
  │  • Copy to data/raw/<run_ts>/            │
  │  • Insert into raw_files (idempotent)    │
  │  • Create run record in runs             │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 3 — Profile                       │
  │  • Detect delimiter, encoding, headers   │
  │  • Save data/profiles/<hash>.json        │
  │  • Update raw_files metadata             │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 4 — Map → Stage                   │
  │  • Load mapping YAML (bank_key)          │
  │  • Rename columns per column_map         │
  │  • Drop unwanted columns                 │
  │  • Insert TEXT rows into                 │
  │    transactions_stage (raw, no parsing)  │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 5 — Normalize (Python)            │
  │  • Parse amount (Decimal, 4 families)    │
  │  • Parse dates (fail on ambiguity)       │
  │  • Normalize description text            │
  │  • Compute transaction_fingerprint       │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 6 — Validate (gate)               │
  │  • Check required fields non-null        │
  │  • Check amount is valid Decimal         │
  │  • Warn on large txns / missing category │
  │  • Save data/validation/<run_id>.json    │
  │  • FAIL RUN if any critical errors       │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 7 — Load (dedupe)                 │
  │  • INSERT OR IGNORE into                 │
  │    transactions_norm                     │
  │  • UNIQUE(transaction_fingerprint)       │
  │    prevents duplicates on re-run         │
  │  • Update runs with row counts           │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 8 — Parquet Snapshot              │
  │  • DuckDB COPY TO (FORMAT PARQUET, ZSTD) │
  │  • Partitioned by year/month             │
  │  • data/master/transactions_norm/        │
  │    year=YYYY/month=MM/part-*.parquet     │
  └───────────────────┬──────────────────────┘
                      │
                      ▼
  ┌──────────────────────────────────────────┐
  │  Stage 9 — Analytics Exports             │
  │  • Read from Parquet (or DuckDB table)   │
  │  • Export 5 standard CSV reports to      │
  │    data/reports/                         │
  └──────────────────────────────────────────┘
```

---

## Database Tables

### `raw_files`
Idempotency anchor. One row per unique file (keyed by SHA-256 hash). Re-running with the same file is safe — the row is skipped.

### `runs`
Audit ledger. One row per pipeline execution. Records row counts at each stage and final status (success/fail).

### `transactions_stage`
Intermediate staging table. Stores raw TEXT values after column mapping but before normalization. Useful for debugging parse failures.

### `transactions_norm`
Canonical normalized table. Strongly typed (DATE, DECIMAL). Enforces `UNIQUE(transaction_fingerprint)` to prevent duplicate rows.

---

## Transaction Fingerprint

The fingerprint is a SHA-256 hash over:

```
bank_name | account_id | transaction_date | UPPER(TRIM(description)) | amount | currency
```

This provides **business identity** (not file-row identity). Two files with the same transaction will produce the same fingerprint and the second insert will be silently skipped.

---

## Amount Sign Convention

| Direction | Sign | Example |
|---|---|---|
| Purchase / outflow | **negative** | `-42.99` |
| Payment / inflow | **positive** | `+1500.00` |

All four amount families (`signed`, `debit_credit`, `money_in_out`, `amount_plus_flag`) are normalized to this convention in `utils/money.py`.

---

## Parquet Layer

The Parquet snapshot at `data/master/transactions_norm/` is the preferred source for analytics queries. It uses Hive-style partitioning (`year=YYYY/month=MM`) which enables DuckDB partition pruning on date-range queries.

The DuckDB table is the authoritative source; Parquet is a derived, read-optimized copy.
