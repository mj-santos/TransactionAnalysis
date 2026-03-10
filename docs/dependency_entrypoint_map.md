# Dependency + Entrypoint Map

## 1) Entrypoints and dependency chain

### CLI entrypoint
- Console script: `finance_etl = finance_etl.cli:main`.
- Primary operational commands:
  - `finance_etl run` -> delegates to `pipeline.run_with_options(...)`
  - `finance_etl ingest`
  - `finance_etl validate`
  - `finance_etl parquet`
  - `finance_etl analytics`
  - `finance_etl api`

### Programmatic entrypoint
- Stable library API: `pipeline.run(inputs, mapping_dir, db_path) -> run_id`.
- Advanced API: `pipeline.run_with_options(...) -> RunResult`.

### Web API entrypoint
- FastAPI app factory: `api.create_app(...)`.
- Endpoints:
  - `POST /runs`
  - `GET /runs/{run_id}`
  - `GET /reports`
  - `GET /reports/{name}`
  - `GET /charts/{name}`

## 2) Module graph (run path)

```text
cli.cmd_run
  -> pipeline.run_with_options
     -> db.get_connection
     -> ingest.create_run
     -> ingest.register_files
     -> profile.profile_file
        -> utils.csv_sniff.sniff_csv
     -> mapping.load_mapping
        -> models.parse_mapping_config
     -> mapping.map_and_stage
     -> normalize.normalize_staged_rows
        -> utils.money.*
        -> utils.dates.parse_date
        -> utils.text.normalize_description
        -> utils.fingerprint.compute_fingerprint
     -> validate.validate_normalized
     -> load.load_normalized
     -> parquet.refresh_parquet
     -> analytics.run_analytics
     -> ingest.finalize_run
```

## 3) DB interaction map

### Schema bootstrap
- `db.get_connection(...)` bootstraps:
  - `raw_files`
  - `runs`
  - `transactions_stage`
  - `transactions_norm` + unique index on `transaction_fingerprint`

### Write path per run
1. `ingest.create_run` inserts `runs(status='running')`.
2. `ingest.register_files` inserts/updates `raw_files` idempotently by `file_hash`.
3. `mapping.map_and_stage` inserts row-level raw text to `transactions_stage`.
4. `load.load_normalized` inserts canonical rows into `transactions_norm` with duplicate skip behavior from unique fingerprint.
5. `ingest.finalize_run` updates final run counters/status/notes.

## 4) One run end-to-end with failure points

1. Resolve mapping (`mapping_path` or `bank_key`).
   - Failure: mapping missing/invalid family/invalid typed config.
2. Open DB + create run record.
   - Failure: duplicate `run_id` or DB unavailable.
3. Register raw files.
   - Failure: missing input file, read/copy error, SQL write error.
4. Profile files.
   - Failure: encoding/sniff/read failure, malformed CSV.
5. Map + stage rows.
   - Failure: required source columns absent, CSV/header mismatch, stage insert error.
6. Normalize rows.
   - Failure: amount parse error, date parse/ambiguity error, empty normalized description.
7. Validate rows.
   - Failure: critical rule violations (required fields/amount validity), run aborts.
8. Load normalized rows.
   - Non-fatal row-level failures logged/skipped; duplicates skipped by fingerprint uniqueness.
9. Parquet refresh.
   - Failure: file/permission issues, DuckDB COPY failure.
10. Analytics export.
   - Failure: query/export failures per report.
11. Finalize run.
   - Failure: invalid status or missing run row update.

## 5) Invariants to protect and enforcement locations

1. **Sign convention**: outflow negative, inflow positive.
   - Enforced in `utils.money` family parsers.
2. **No float money math**: `Decimal` parsing + string insertion at load.
   - Enforced in `utils.money` and `load.load_normalized`.
3. **Date ambiguity fails fast**.
   - Enforced in `utils.dates.parse_date` (requires locale or explicit format).
4. **Idempotent file ingest**.
   - Enforced by `raw_files.file_hash` primary key + ingest check.
5. **Idempotent normalized load**.
   - Enforced by unique `transaction_fingerprint` index + `INSERT OR IGNORE`.
6. **Mapping schema sanity**.
   - Enforced by typed parser `models.parse_mapping_config` from `mapping.load_mapping`.
7. **Run ledger integrity**.
   - Enforced by `create_run` duplicate check + `finalize_run` status/affected-row checks.

## 6) Minimal FastAPI layer (recommended boundary)

Keep API thin and orchestration-only:
- `POST /runs`
  - Input: file paths + mapping selector
  - Action: call `pipeline.run_with_options(...)`
  - Output: `run_id`, counts
- `GET /runs/{run_id}`
  - Action: call `pipeline.get_run_status(...)`
  - Output: status/counters/timings
- `GET /reports`
  - Action: list report CSVs
- `GET /reports/{name}`
  - Action: stream report CSV
- `GET /charts/{name}`
  - Action: CSV->JSON via `chart_from_report_csv(...)`

No business logic duplication in API handlers.

## 7) Mobile-first PWA page/component proposal

### Pages
1. **Runs** (default)
   - list recent runs, status chips, row counts, error counts
2. **Run Detail**
   - stage timings, validation errors/warnings, linked outputs
3. **Reports**
   - report cards + quick preview table + download actions
4. **Dashboards**
   - month/category/merchant pivots with filters
5. **Settings**
   - mappings directory, DB path, report directory, date defaults

### Components
- `RunStatusCard`, `StageTimingList`, `ValidationIssueTable`
- `FilterBar` (account/date/category)
- `PivotGrid` + `ChartPanel`
- `ExportActions` (CSV/Parquet)
- `OfflineBadge` + `SyncState`

### PWA requirements
- Service worker for shell + selected report cache
- Install prompt + manifest icons/theme
- Offline read mode for cached reports/charts
- Background refresh when connectivity returns
