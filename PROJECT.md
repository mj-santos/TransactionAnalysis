# PROJECT.md — Spendly (package: finance_etl)
> Persistent memory and source of truth for all development sessions.
> **Update this file whenever features, schema, or file structure change.**

---

## 1. APP OVERVIEW

**Spendly** (Python package: `finance_etl`) is a fully local, deterministic ETL pipeline and web dashboard for importing, normalizing, categorizing, and analyzing personal bank and credit-card transaction CSVs. It runs entirely on the user's machine — no cloud, no sync, no external services. All data lives in a single DuckDB file on disk.

**Who it's for:** Individual users who export CSVs from their bank(s) and want a structured, queryable ledger with analytics, merchant normalization, and category tracking.

**How it's used:** User runs `finance_etl api` (or Docker) to start the FastAPI server, then opens the web UI at `localhost:8000`. They upload CSV files through the browser, map columns via a 3-step wizard, and the pipeline ingests, normalizes, validates, and loads transactions into the local DuckDB. All subsequent analysis, rule management, and reporting happens through the same browser UI.

**Architecture notes:**
- Zero cloud dependencies. No user accounts, no telemetry.
- Single DuckDB file at `data/db/finance.duckdb` holds all data.
- The web UI is a single-page app served by the FastAPI backend directly (no separate frontend build step).
- Background jobs (normalization, category apply) run in Python threads; the UI polls for status.

---

## 2. TECH STACK

| Layer | Technology | Version / Notes |
|---|---|---|
| Language | Python | 3.11+ required (3.12 in Docker) |
| Web framework | FastAPI | ≥0.115 — serves API + static web UI |
| ASGI server | Uvicorn | ≥0.30 |
| Database | DuckDB | ≥0.10 — embedded, file-based SQL OLAP |
| Data interchange | PyArrow | ≥14.0 — used for Parquet export |
| Config format | YAML | PyYAML ≥6.0 — mapping profiles and category rules |
| CLI framework | Click | ≥8.1 — `finance_etl` command group |
| File encoding detection | Chardet | ≥5.0 — auto-detect CSV encoding |
| File upload | python-multipart | ≥0.0.9 — required by FastAPI for `UploadFile` |
| ML (optional) | scikit-learn | ≥1.3 — install with `pip install -e ".[wizard]"` for K-Means category clustering in `wizard/category_suggestion.py`. Falls back to word-frequency without it. |
| UI stack | Vanilla HTML/CSS/JS | No framework. Single HTML file + 2 JS files + 1 CSS file. |
| Containerization | Docker + docker-compose | Python 3.12-slim base; data volume at `/app/data` |
| Packaging | setuptools (pyproject.toml) | Installable as `finance_etl` package; entry point: `finance_etl.cli:main` |
| Testing | pytest | Config in `pytest.ini`; tests in `tests/` |

**Design system (CSS variables in `style.css`):**
- Sidebar: `#0f172a` (dark navy), 220px wide
- Primary blue: `#3b82f6`, hover `#2563eb`
- Success: `#22c55e`, Danger: `#ef4444`, Warning: `#f59e0b`, Staged: `#8b5cf6`
- Font: system-ui stack (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`)
- Border radius: `8px`, Shadow: `0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06)`

---

## 3. FOLDER & FILE STRUCTURE

```
TransactionAnalysis/
├── PROJECT.md                  ← this file
├── README.md                   ← user-facing install/usage guide
├── pyproject.toml              ← package metadata, dependencies, pytest config
├── Dockerfile                  ← Python 3.12-slim; installs package; data/ is a VOLUME
├── docker-compose.yml          ← single service: finance-etl-api on port 8000
├── run_dev.py                  ← dev convenience: starts uvicorn directly
├── setup_wizard.py             ← standalone CLI wizard (legacy; duplicated by web wizard)
├── conftest.py                 ← pytest path fix: inserts src/ into sys.path so tests can find finance_etl without pip install
├── pytest.ini                  ← pytest config (duplicates pyproject.toml [tool.pytest.ini_options])
├── install.sh                  ← bash installer for non-Docker usage
├── .env / .env.example         ← API host/port overrides
├── .github/workflows/
│   └── docker-publish.yml      ← publishes Docker image to registry on push
│
├── config/
│   └── mappings/               ← YAML bank column mapping files (used by CLI; wizard generates these)
│       ├── example_debit_credit.yaml
│       └── example_signed_amount.yaml
│
├── data/                       ← runtime data (gitignored in prod)
│   ├── auto_backups/           ← auto-backup JSON files (max 5, rotated); created on every commit
│   ├── db/finance.duckdb       ← THE database — all user data lives here
│   ├── logs/                   ← per-run log files (UUID-named) + api.log
│   ├── master/                 ← Parquet snapshot exports (Hive-partitioned by year/month)
│   ├── profiles/               ← per-file JSON profiling results (encoding, delimiter, headers)
│   ├── raw/                    ← copies of uploaded CSVs stored by run timestamp
│   ├── reports/                ← CSV analytics exports (regenerated after each run)
│   ├── uploads/                ← uploaded files (short-lived; used as pipeline inputs)
│   └── validation/             ← per-run validation JSON reports
│
├── docs/                       ← developer documentation (not user-facing)
│   ├── architecture.md
│   ├── CONFIG.md
│   ├── DEVELOPMENT.md
│   ├── INSTALL.md
│   ├── NEXT_PHASE_READINESS.md
│   ├── USER_GUIDE.md
│   ├── config_examples.md
│   ├── dependency_entrypoint_map.md
│   └── refactor_plan.md
│
├── src/finance_etl/            ← main Python package
│   ├── __init__.py
│   ├── api.py                  ← FastAPI app factory (create_app); ALL endpoints defined here (~3022 lines)
│   ├── analytics.py            ← Stage 9: SQL analytics queries → CSV reports
│   ├── backup_migrations.py    ← Backup payload migration chain (v1→v2); CURRENT_BACKUP_VERSION
│   ├── category_rules.py       ← Category normalization engine + BUILT_IN_CATEGORY_MAP (~97 entries)
│   ├── cli.py                  ← Click CLI: run, ingest, validate, parquet, analytics, api, wizard
│   ├── db.py                   ← DuckDB connection factory + DDL + migrations
│   ├── ingest.py               ← Stage 1-2: file registration, run creation, raw copy
│   ├── load.py                 ← Stage 7: insert normalized rows into transactions_norm
│   ├── mapping.py              ← Stage 3-4: load YAML mapping, map CSV rows → stage rows
│   ├── merchant_rules.py       ← Merchant normalization engine + category suggestions
│   ├── models.py               ← Typed dataclasses: MappingConfig, DateConfig, AmountConfig
│   ├── normalize.py            ← Stage 5: normalize staged rows (amounts, dates, CC subtype)
│   ├── parquet.py              ← Stage 8: export transactions_norm → partitioned Parquet
│   ├── pipeline.py             ← Orchestrator: run_with_options(), commit_run(), RunResult
│   ├── recurring.py            ← Recurring transaction detection engine + monthly cost calculation
│   ├── profile.py              ← Stage 2: detect encoding, delimiter, headers; write profile JSON
│   ├── validate.py             ← Stage 6: validate normalized rows; flag errors/warnings
│   ├── wizard_mapping.py       ← Wizard business logic: header inference, profile merge, YAML save
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── csv_preprocess.py   ← CSV cleaning before parsing (BOM removal, encoding fixes, header/metadata strip)
│   │   ├── csv_sniff.py        ← Delimiter and quoting auto-detection
│   │   ├── dates.py            ← Date parsing with format hint support
│   │   ├── fingerprint.py      ← Deterministic transaction_fingerprint generation (SHA-256)
│   │   ├── hashing.py          ← File content SHA-256 hashing
│   │   ├── log.py              ← Logger factory (per-run file handlers)
│   │   ├── money.py            ← Amount string parsing → Decimal (signed, debit/credit, in/out, flag)
│   │   └── text.py             ← Text normalization utilities
│   │
│   ├── wizard/                 ← PARTIALLY SUPERSEDED by wizard_mapping.py + web wizard
│   │   ├── __init__.py
│   │   ├── category_suggestion.py  ← K-Means / word-freq category clustering (scikit-learn optional)
│   │   ├── header_inference.py     ← Keyword-based CSV header → canonical field mapping
│   │   ├── mapping_rules.py        ← Vendor extraction + rule generation from descriptions
│   │   └── setup_wizard.py         ← CLI interactive wizard (called by `finance_etl wizard`)
│   │
│   └── web/
│       ├── index.html          ← Single-page UI (1,146 lines); all pages embedded as hidden sections
│       └── static/
│           ├── app.js          ← All UI logic (~3,248 lines); no bundler/framework
│           ├── style.css       ← All styles (~728 lines)
│           └── table_controls.js ← Two reusable widgets (~279 lines):
│                                   makeSourceDropdown() — Import Source radio-dropdown
│                                   renderTxnTotals()   — pinned tfoot totals row (CC + bank)
│
└── tests/
    ├── __init__.py             ← package marker only (empty)
    ├── fixtures/               ← test CSVs and golden output JSON
    │   ├── golden/
    │   │   ├── expected_norm.json
    │   │   └── signed_weird.csv
    │   ├── nonstandard_headers.csv
    │   └── standard_headers.csv
    ├── smoke_test_wizard.py    ← smoke test for wizard profile matching
    ├── test_backup_restore.py  ← v2 backup migration, roundtrip, rotation tests
    ├── test_csv_upload_hardening.py ← 6-case upload pipeline tests (encoding, BOM, CRLF, delimiters, Excel, extension)
    ├── test_dates.py
    ├── test_fingerprint.py
    ├── test_golden_pipeline.py
    ├── test_ingest.py
    ├── test_mapping.py
    ├── test_models.py
    ├── test_money.py
    ├── test_pipeline_api.py
    ├── test_recurring.py       ← recurring detection engine tests
    └── test_wizard_mapping.py
```

**Potentially unused / orphaned files:**
- `setup_wizard.py` (repo root) — standalone script that duplicates `src/finance_etl/wizard/setup_wizard.py`; the web wizard has superseded both.
- `src/finance_etl/wizard/` — the subpackage is only invoked via `cli.py`'s `finance_etl wizard` command. No web API endpoint references the `wizard/` subpackage directly. If the CLI wizard command is removed, the entire `wizard/` subpackage becomes dead code.
- `pytest.ini` — duplicates the `[tool.pytest.ini_options]` block in `pyproject.toml` with identical settings. pytest picks up `pytest.ini` first; the `pyproject.toml` section is redundant.
- `config/wizard_profiles/` — referenced in PROJECT.md v1 tree but the directory does not exist in the repository (created at runtime by the wizard).

---

## 4. FEATURE INVENTORY

### UI Tabs (sidebar navigation)

| Tab | Page ID | Loads on navigate | Status |
|---|---|---|---|
| Dashboard | `#page-dashboard` | `loadDashboard()` on boot | ✅ Working |
| Import | `#page-import` | (upload is event-driven) | ✅ Working |
| History | `#page-history` | `loadHistory()` | ✅ Working |
| Credit Cards | `#page-credit-cards` | `loadTxnTab('credit_card')` | ✅ Working |
| Bank Transactions | `#page-bank-transactions` | `loadTxnTab('bank')` | ✅ Working |
| Cash Flow | `#page-cashflow` | `loadCashFlow()` | ✅ Working |
| Reports | `#page-reports` | `loadReports()` | ✅ Working |
| Merchants | `#page-merchant-rules` | `loadMerchantRules()`, `loadUncategorized()` | ✅ Working |
| Categories | `#page-category-rules` | `loadCategoryRules()` | ✅ Working (BUG-1 fixed) |
| Recurring | `#page-recurring-transactions` | `loadRecurringTransactions()` | ✅ Working |
| Settings | `#page-settings` | `loadSettings()` | ✅ Working (BUG-3 fixed) |

### Feature Details

**Dashboard (`#page-dashboard`)**
- MTD spend KPI card, transaction count card, unreviewed count KPI card
- Month navigation (prev/next arrows) — `dashboardPrevMonth()`, `dashboardNextMonth()`
- Top categories bar chart (horizontal, CSS-rendered)
- Budget tracker with inline add/edit/delete form — `openBudgetForm()`, `saveBudget()`, `deleteBudget()`
- Budget rebalance suggestions — `loadRebalanceSuggestions()`, `applyRebalance()`: analyses avg monthly spend vs budget, suggests adjustments for categories >=15% over/under, user selects and confirms before applying
- Recent transactions table (last 10) with unreviewed dot indicators
- Unreviewed count badge on sidebar Dashboard nav link
- API: `GET /dashboard/summary?year=&month=`, `GET /budgets/rebalance`, `POST /budgets/rebalance/apply`

**Import (`#page-import`)**
- Drag-and-drop CSV upload zone; multi-file supported
- File chip UI showing upload status
- Triggers 3-step Mapping Wizard automatically after upload
- Run status card with polling (pending → running → staged → success/failed)
- Staged preview table (first 200 rows)
- Commit / Discard buttons on staged runs
- Reset import button
- API: `POST /upload`, `POST /runs`, `GET /runs/{id}`, `GET /runs/{id}/preview`, `POST /runs/{id}/commit`

**Mapping Wizard (modal overlay)**
- Step 1: Detect headers, select statement type (credit card / bank), confirm CC polarity
- Step 2: Map CSV columns to canonical fields; amount group auto-lock logic
- Step 3: Summary review before running
- Profile matching: auto-fills from saved YAML if institution/account recognized
- Profile persistence: wizard profile saved/merged after each run
- API: `POST /wizard/detect`, `POST /wizard/validate`, `POST /wizard/save-and-run`, `GET /wizard/profiles`

**History (`#page-history`)**
- Table of all import runs with status badges
- Per-run: view preview, commit from history, delete run (with option to preserve transactions)
- Delete modal with "keep transactions" checkbox
- API: `GET /runs`, `GET /runs/{id}/preview`, `POST /runs/{id}/commit`, `DELETE /runs/{id}`

**Credit Cards / Bank Transactions (separate tabs, identical feature set)**
- Filter bar: date range, description search, merchant filter, category filter, account filter
- Quick date preset buttons: This Month, Last Month, 3 Months, YTD, All
- Import Source dropdown (per statement type)
- Group-by selector (including `category_normalized`, `category_parent`)
- "Show Unreviewed Only" toggle filter
- Sortable columns
- Infinite scroll / "Load more" (100 rows per page)
- Totals footer row
- Per-transaction "Mark as Reviewed" button with unreviewed dot indicator
- "Mark All Reviewed" bulk action (respects current filters)
- API: `GET /transactions`, `GET /transactions/totals`, `GET /transactions/sources`, `POST /transactions/mark-reviewed`, `POST /transactions/mark-all-reviewed`

**Cash Flow (`#page-cashflow`)**
- Summary KPI cards: Income (green), Spending (red), Net (color-coded), Month-over-Month delta
- Time period filter dropdown: This Month, Last Month, Last 3 Months, Last 12 Months, Custom Range
- Custom date range inputs (shown when "Custom Range" selected)
- Toggleable "Include transfers" checkbox (excludes payment subtypes and transfer categories by default)
- Monthly bar chart: paired income/spending bars per month, CSS-rendered (no Chart.js dependency)
- Spending by category breakdown: horizontal bars with percentage labels (top 12)
- Monthly detail table: Income, Spending, Net per month with color-coded values
- Month-over-month delta indicator showing spending change vs prior month
- API: `GET /cashflow/summary?period=&start_date=&end_date=&include_transfers=`

**Reports (`#page-reports`)**
- Static report cards: spend_by_month_category, cashflow_by_month, spend_by_merchant, totals_by_account, top_merchants
- Per-report: view as chart (bar, time-series), download CSV
- Chart viewer with group-by and date-from/date-to filters
- Custom Report Builder: add/remove filters, group-by, bucket (day/week/month/year), order-by, limit
- Quick date presets in custom report
- Results rendered as table with download-to-CSV button
- API: `GET /reports`, `GET /reports/{name}`, `GET /charts/{name}`, `POST /reports/query`, `GET /metric-docs/{topic}`

**Merchants (`#page-merchant-rules`)**
- Recommended Normalization Rules panel: `loadRuleSuggestions()` → `GET /merchant-rules/suggestions`
  - Analyzes raw descriptions; suggests pattern → merchant rules
  - Accept, Edit, Dismiss per suggestion; Accept All
- Merchant Normalization Rules CRUD table: `loadMerchantRules()` → `GET /merchant-rules`
  - Add/Edit rules with compound AND/OR conditions, match types (contains/startswith/regex), priority, negation
  - Test rule against live data; paginated match results
  - Delete with confirmation
- Re-normalize All Transactions button: `startRenormalize()` → `POST /normalize/apply` (background job, polled)
- Uncategorized Merchants panel: `loadUncategorized()` → `GET /merchant-categories/uncategorized`
  - Inline category assignment dropdown + assign button per merchant
  - Backfills category onto all transactions for that merchant
- API: Full CRUD on `/merchant-rules`, `/merchant-categories`, `/normalize/apply`, `/normalize/{job_id}`

**Categories (`#page-category-rules`)**
- Suggested Category Mappings panel: `loadCatSuggestions()` → `GET /category-rules/suggestions`
  - Scans raw bank category strings; matches against built-in taxonomy
  - Accept (creates rule), Edit (opens form), Dismiss per suggestion; Accept All
- Suggested Merchant Categories panel: `loadCategorySuggestions()` → `GET /merchant-categories/suggestions`
  - Keyword-heuristic matching of merchant names to categories
  - Accept assigns category to merchant via `/merchant-categories`
- Category Normalization Rules CRUD table: `loadCategoryRules()` → `GET /category-rules`
  - Maps raw bank category → normalized category + parent group
  - Inline editor form with parent group dropdown (fixed list of 12 parents)
- Apply Normalization button: `startCategoryNormalize()` → `POST /category-rules/apply` (background job)
  - ~~**❌ BROKEN**: polling fixed in v2.1.1 (BUG-1)~~
- API: Full CRUD on `/category-rules`, `/category-rules/apply`, `/category-rules/suggestions`, `/merchant-categories/suggestions`

**Recurring Transactions (`#page-recurring-transactions`)**
- Auto-detection engine: groups by normalized merchant, analyses interval regularity + amount consistency
- Confidence threshold: patterns flagged only with 3+ occurrences, <35% interval CV, <30% amount CV
- Frequency classification: weekly, biweekly, monthly, quarterly, annual, irregular
- Monthly Recurring Cost KPI card — total estimated monthly cost across all detected recurring charges
- Recurring charges table: merchant, amount, frequency badge, last charged, next estimated date, hit count
- Auto/manual badge per row distinguishing auto-detected vs user-overridden entries
- Unmark button per row to exclude a merchant from the recurring list
- Manual mark form: text input + button to force-mark any merchant as recurring
- User overrides stored in `recurring_overrides` DB table; take precedence over auto-detection
- Included in v2 backup/restore system
- Detection engine: `src/finance_etl/recurring.py`
- API: `GET /recurring`, `POST /recurring/override`, `DELETE /recurring/override/{merchant}`

**Settings (`#page-settings`)**
- Verbose API error messages toggle
- Show logs panel on error toggle
- Save settings button — `PATCH /settings`
- Refresh logs button — `GET /logs`
- Download log file link — `GET /logs/download`
- Backend logs panel (pre-formatted, last 200 lines)
- **Data Backup & Restore** card (v2):
  - Version badge (v2) in card header
  - Last auto-backup timestamp and count display — `loadBackupStatus()` → `GET /backup/status`
  - Current database table row counts grid
  - Download Full Backup (JSON) button — `downloadBackup()` → `GET /backup/export`
    - Exports all 9 tables + wizard profile YAML files; timestamped filename
  - File picker with preview modal — `previewBackup()` → client-side JSON parse
    - Shows backup version, creation date, row counts per table before confirming
    - `confirmRestore()` → `POST /backup/restore`; auto-snapshot saved before overwriting
    - Supports v1 (legacy) and v2 backup files; v1 auto-migrated to v2 on restore
  - Auto-backup on every successful import commit (max 5 rotated in `data/auto_backups/`)
- ~~**⚠️ Settings were in-memory only** — fixed in v2.1.3 (BUG-3); now persisted to `data/ui_settings.json`~~
- API: `GET /backup/export`, `POST /backup/restore`, `GET /backup/status`

---

## 5. DATA MODELS & SCHEMA

All tables live in `data/db/finance.duckdb`. Schema is bootstrapped and migrated in `db.py`.

### `transactions_norm` — the ledger (primary data table)

| Column | Type | Notes |
|---|---|---|
| `transaction_date` | DATE NOT NULL | Parsed transaction date |
| `posted_date` | DATE | Posting date (optional) |
| `description` | TEXT NOT NULL | Raw description from CSV |
| `merchant` | TEXT | Normalized merchant name (applied by merchant rules) |
| `category` | TEXT | Raw bank category string from CSV |
| `amount` | DECIMAL(18,2) NOT NULL | Signed amount (negative = debit for signed format) |
| `currency` | TEXT DEFAULT 'USD' | Currency code |
| `bank_name` | TEXT NOT NULL | From mapping config |
| `account_name` | TEXT NOT NULL | From mapping config or user input |
| `account_id` | TEXT NOT NULL | From mapping config or user input |
| `source_file` | TEXT NOT NULL | Original filename |
| `source_row` | INTEGER NOT NULL | Row number in source CSV |
| `file_hash` | TEXT NOT NULL | SHA-256 of source file content |
| `transaction_fingerprint` | TEXT NOT NULL | Deterministic dedup key |
| `ingested_at` | TIMESTAMP DEFAULT NOW | When the row was loaded |
| `statement_type` | TEXT | `'credit_card'` or `'bank'` (added by migration) |
| `run_id` | TEXT | FK to `runs.run_id` (added by migration) |
| `transaction_subtype` | TEXT | `'spending'`, `'payment'`, `'adjustment'`, or NULL (bank) (added by migration) |
| `resolved_amount` | DECIMAL(18,2) | Always ≥ 0; direction encoded in `transaction_subtype` (added by migration) |
| `category_normalized` | TEXT | Normalized category from category rules (added by migration) |
| `category_parent` | TEXT | Parent group (e.g. "Food & Dining") from category rules (added by migration) |
| `unreviewed` | BOOLEAN DEFAULT TRUE | Review tracking flag (added by migration) |

**Index:** `UNIQUE INDEX idx_tx_fingerprint ON transactions_norm(transaction_fingerprint)`

**Key relationships:**
- `file_hash` → `raw_files.file_hash`
- `run_id` → `runs.run_id`
- `merchant` → `merchant_category_map.merchant` (soft, not enforced)
- `category` → `category_rules.raw_category` (soft, not enforced)

**⚠️ Schema notes:**
- 7 columns exist only via migration, not in base DDL: `statement_type`, `run_id`, `transaction_subtype`, `resolved_amount`, `category_normalized`, `category_parent`, `unreviewed`
- No explicit UNIQUE constraint on `transaction_fingerprint` in DDL — dedup relies on the separate CREATE UNIQUE INDEX statement

---

### `transactions_stage` — temporary staging area

| Column | Type | Notes |
|---|---|---|
| `run_id` | TEXT | Links to `runs` |
| `file_hash` | TEXT | Links to `raw_files` |
| `source_file` | TEXT | Original filename |
| `source_row` | INTEGER | Row number in CSV |
| `bank_name` | TEXT | |
| `account_name` | TEXT | |
| `account_id` | TEXT | |
| `transaction_date_raw` | TEXT | Unparsed date string from CSV |
| `posted_date_raw` | TEXT | |
| `description_raw` | TEXT | |
| `amount_raw` | TEXT | |
| `debit_raw` | TEXT | |
| `credit_raw` | TEXT | |
| `money_in_raw` | TEXT | |
| `money_out_raw` | TEXT | |
| `dc_flag_raw` | TEXT | Debit/Credit flag column value |
| `currency_raw` | TEXT | |
| `extra_json` | TEXT | Unmapped columns as JSON |
| `amount_debit_raw` | TEXT | In base DDL |
| `amount_credit_raw` | TEXT | In base DDL |

Rows exist only during preview phase; deleted after commit or discard.

---

### `runs` — import run ledger

| Column | Type | Source | Notes |
|---|---|---|---|
| `run_id` | TEXT PK | Base DDL | UUID |
| `started_at` | TIMESTAMP | Base DDL | |
| `finished_at` | TIMESTAMP | Base DDL | |
| `status` | TEXT | Base DDL | `pending`, `running`, `staged`, `committing`, `success`, `failed` |
| `statement_type` | TEXT | Base DDL + migration | `'credit_card'` or `'bank'` |
| `run_label` | TEXT | Base DDL + migration | Human-readable label |
| `files_count` | INTEGER | Base DDL | |
| `rows_in` | BIGINT | Base DDL | |
| `rows_staged` | BIGINT | Base DDL | |
| `rows_normalized` | BIGINT | Base DDL | |
| `rows_loaded` | BIGINT | Base DDL | |
| `errors_count` | INTEGER | Base DDL | |
| `notes` | TEXT | Base DDL | |
| `imported_file` | TEXT | Base DDL | Filename of uploaded file |

---

### `raw_files` — uploaded file registry

| Column | Type | Notes |
|---|---|---|
| `file_hash` | TEXT PK | SHA-256 |
| `original_path` | TEXT | Original upload path |
| `ingested_path` | TEXT | Path in `data/raw/` |
| `ingested_at` | TIMESTAMP | |
| `file_size_bytes` | BIGINT | |
| `delimiter` | TEXT | Detected delimiter |
| `encoding` | TEXT | Detected encoding |
| `header_json` | TEXT | JSON array of column headers |
| `profile_path` | TEXT | Path to profiling JSON in `data/profiles/` |

---

### `merchant_rules` — merchant normalization rules

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `pattern` | TEXT NOT NULL | Match pattern string |
| `match_type` | TEXT DEFAULT 'contains' | `'contains'`, `'startswith'`, `'regex'` |
| `merchant` | TEXT NOT NULL | Target normalized merchant name |
| `priority` | INTEGER DEFAULT 0 | Higher = applied first |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| `conditions` | TEXT | JSON array of `{pattern, match_type, negate}` for compound rules (added by migration) |
| `logic` | TEXT DEFAULT 'AND' | `'AND'` or `'OR'` for combining conditions (added by migration) |

Applied in order: `priority DESC, id ASC`. First matching rule wins.

---

### `merchant_category_map` — merchant → category assignments

| Column | Type | Notes |
|---|---|---|
| `merchant` | TEXT PK | Normalized merchant name |
| `category` | TEXT NOT NULL | Assigned category |
| `source` | TEXT DEFAULT 'user' | `'user'` (manual, never overwritten) or `'learned'` (auto) |
| `updated_at` | TEXT | ISO timestamp |

---

### `category_rules` — raw bank category → normalized category

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `raw_category` | TEXT NOT NULL UNIQUE | Raw bank category string (case-insensitive match) |
| `category` | TEXT NOT NULL | Normalized subcategory (e.g. "Restaurants") |
| `parent` | TEXT NOT NULL | Parent group (e.g. "Food & Dining") |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

Lookup priority: user rules (DB) > built-in `BUILT_IN_CATEGORY_MAP` in `category_rules.py` > fallback (keep raw, assign parent "Other").

**Built-in taxonomy covers ~97 raw category strings** across 12 parent groups: Food & Dining, Shopping, Travel, Transportation, Entertainment, Health & Wellness, Bills & Utilities, Financial, Education, Home, Gifts & Charity, Other.

---

### `budget_goals` — monthly budget targets

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `parent` | TEXT NOT NULL | Parent category group |
| `category` | TEXT | Subcategory (NULL = applies to entire parent) |
| `monthly_amount` | DECIMAL(18,2) NOT NULL | Target budget in USD |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

**Unique constraint:** `(parent, category)`

---

### `normalization_jobs` — background job tracking

| Column | Type | Notes |
|---|---|---|
| `job_id` | TEXT PK | UUID or prefixed UUID hex |
| `status` | TEXT DEFAULT 'pending' | `'pending'`, `'running'`, `'success'`, `'failed'` |
| `rows_total` | BIGINT | |
| `rows_done` | BIGINT DEFAULT 0 | |
| `error` | TEXT | Error message if failed |
| `started_at` | TEXT | ISO timestamp |
| `finished_at` | TEXT | ISO timestamp |
| `created_at` | TEXT NOT NULL | ISO timestamp |

Used by both merchant renormalization (`batch_renormalize`) and category normalization (`apply_category_rules`). Job IDs are prefixed differently: merchant jobs use `"norm_"` prefix; category jobs use `"catnorm_"` prefix. Both are polled via `GET /normalize/{job_id}`.

---

### `recurring_overrides` — user manual recurring mark/unmark

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `merchant_key` | TEXT NOT NULL UNIQUE | Normalized merchant name |
| `is_recurring` | BOOLEAN NOT NULL | `TRUE` = force-mark, `FALSE` = force-unmark |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

---

### `schema_version` — DuckDB schema version tracking

| Column | Type | Notes |
|---|---|---|
| `version` | INTEGER NOT NULL | Current schema version number |

Single-row table seeded with `1` on first migration run.

---

### Python Config Models (`models.py`)

| Model | Purpose |
|---|---|
| `MappingConfig` | Typed config for a bank's CSV mapping (frozen dataclass) |
| `DateConfig` | Date column mapping and format |
| `AmountConfig` | Amount column mapping per family |
| `AmountFamily` | Literal type: `"signed"` \| `"debit_credit"` \| `"money_in_out"` \| `"amount_plus_flag"` |

---

## 6. KNOWN ISSUES & TECH DEBT

### Critical Bugs

**BUG-1: Category normalization polling calls non-existent endpoint**
- File: `app.js`, Line: 3174
- Description: `_pollCatNorm()` polls `GET /category-normalize/${jobId}` but no such endpoint exists in `api.py`. The correct endpoint is `GET /normalize/{job_id}` (which is what merchant renormalization correctly uses at line 2485).
- Impact: After clicking "Apply Normalization" on the Categories page, the job starts successfully but the polling silently fails. The status text never updates — user sees "Job started…" forever. The job runs correctly in the background but the UI never reports completion.
- Fix: Change line 3174 from `/category-normalize/${_catNormJobId}` to `/normalize/${_catNormJobId}`.

**BUG-2: `_staged_runs` dict is in-memory only — staged runs lost on server restart**
- File: `pipeline.py`, Line: 33
- Description: The `_staged_runs: dict[str, dict]` that holds staged pipeline results lives only in the uvicorn process memory. If the server restarts between a user staging a preview and clicking "Commit", the staged data is gone.
- Impact: `GET /runs/{id}` still returns status `'staged'` from the DB, but `POST /runs/{id}/commit` will return 409 Conflict because the dict is empty. The user has no way to recover — they must re-import the file.
- Fix: Persist staged state to disk (e.g. a JSON sidecar file in `data/`) or to a DB table, and restore it on startup.

**BUG-3: `ui_settings` are in-memory only — resets on server restart**
- File: `api.py`, Line: 508
- Description: `app.state.ui_settings` (verbose_logs, show_logs) is initialized to `{verbose_logs: False, show_logs: False}` on every server start. User preferences are lost.
- Impact: Low severity — user must re-enable verbose logs after every restart. Not data-losing, but annoying.
- Fix: Persist settings to a `user_settings` DB table or a JSON file in `data/`.

### Previously Fixed Bugs

**BUG (FIXED): Duplicate function names in `app.js`**
- Merchant-category functions renamed to `acceptMerchantCatSuggestion()` / `dismissMerchantCatSuggestion()`. Category-rules versions (`acceptCatSuggestion()` / `dismissCatSuggestion()`) remain separate.

**BUG (FIXED): `normalization_jobs` status inconsistency**
- Standardized to `'failed'` everywhere. UI polling updated to check `'failed'` (was `'fail'`).

**BUG (FIXED): Backup restore missing compound rule fields**
- Restore INSERT for `merchant_rules` now includes `conditions` and `logic` columns.

**BUG (FIXED): `start_category_normalize` missing `rows_total`**
- The `/category-rules/apply` endpoint now calls `create_category_job()` which pre-computes `rows_total`.

**BUG (FIXED): `transactions_stage` never purged after commit**
- `commit_run()` now deletes staging rows after successful commit.

**BUG-4 (FIXED): Backup restore omits `imported_file` column for runs**
- Added `imported_file` to the restore INSERT statement and to the base DDL.

**BUG-5 (FIXED): Delete run uses `file_hash` from `transactions_stage` which may be empty**
- `DELETE /runs/{run_id}` now deletes from `transactions_norm` by `run_id` directly, with file_hash fallback for legacy rows.

### Hardcoded Values & Workarounds

- **Parent group list** is hardcoded in `index.html` (the `<select id="crf-parent">`) with exactly 12 options. These match `BUILT_IN_CATEGORY_MAP`'s parent groups exactly but are not dynamically derived — adding a new taxonomy parent requires editing both `category_rules.py` and `index.html`.
- **Budget form** (`bf-parent`) uses a free-text `<input>`, NOT a select. No validation against the taxonomy.
- **`min_transactions = 3`** in `analyze_descriptions()` is hardcoded. No UI control.
- **`LARGE_TRANSACTION_THRESHOLD = Decimal("10000.00")`** in `validate.py` is hardcoded.
- ~~**Encoding sample sizes** — standardised to 65,536 bytes in `detect_encoding()` (v2.3.1).~~

### Duplicate Logic

- **Two wizard implementations:** `src/finance_etl/wizard/` subpackage (CLI) and `wizard_mapping.py` (web API) both handle header inference and profile management. They are not unified.
- **`setup_wizard.py` at repo root** duplicates `src/finance_etl/wizard/setup_wizard.py`. Neither is referenced by the web UI.
- **`data/profiles/*.json`** and **`data/validation/*.json`** accumulate indefinitely. There is no cleanup mechanism.
- **Two category suggestion data stores in `app.js`**: `_catSuggestions` (merchant→category, from `/merchant-categories/suggestions`) and `_catSuggestionsData` (raw_category→normalized, from `/category-rules/suggestions`). Variable names are confusingly similar.
- ~~`get_unmapped_categories()` and `get_category_suggestions()` — removed (v2.2.0); api.py implements equivalent logic inline.~~

### Schema Inconsistencies

- ~~`imported_file` column — added to base DDL and backup restore (v2.2.0).~~
- **`category` vs `category_normalized`**: `transactions_norm.category` holds the raw bank category string; `category_normalized` holds the applied rule result. If a transaction was imported without a bank category, `category_normalized` and `category_parent` will be NULL even after running Apply Normalization.
- **`runs.status` value `'committing'`** exists in the UI state machine but is never persisted to the DB — it lives only in the `_async_runs` in-memory dict.

### Dead / Unreferenced Code

- ~~`resolve_category()` — removed (v2.2.0).~~
- ~~`get_unmapped_categories()` — removed (v2.2.0).~~
- ~~`get_category_suggestions()` — removed (v2.2.0).~~
- `src/finance_etl/wizard/category_suggestion.py` — called by `wizard/setup_wizard.py` (CLI path only).
- `src/finance_etl/wizard/mapping_rules.py` — CLI only.
- `src/finance_etl/wizard/header_inference.py` — CLI only; web wizard uses `wizard_mapping.py`.
- ~~`config/categories/rules.yaml` — removed (v2.2.0).~~
- ~~`config/canonical_schema.yaml` — removed (v2.2.0).~~

---

## 7. DECISIONS & CONVENTIONS

### Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Python modules | `snake_case` | `merchant_rules.py`, `category_rules.py` |
| Python functions | `snake_case` | `load_rules()`, `apply_category_rules()` |
| Python classes | `PascalCase` | `CompiledRule`, `MappingConfig` |
| JS functions | `camelCase` | `loadMerchantRules()`, `saveCatRule()` |
| JS private/internal | `_camelCase` prefix | `_renderCatSuggestions()`, `_pollCatNorm()` |
| HTML element IDs | `kebab-case` | `cat-suggest-status`, `crule-suggestions-list` |
| CSS variables | `--kebab-case` | `--sidebar-bg`, `--text-muted` |
| API routes | `kebab-case` | `/merchant-rules`, `/category-rules/suggestions` |
| DB tables | `snake_case` | `transactions_norm`, `merchant_category_map` |
| DB sequences | `seq_<table>_id` | `seq_merchant_rules_id` |

### Architectural Decisions

- **Single HTML file for the entire UI**: No build step, no framework, no module bundler. All 10 pages are `<section class="page">` elements toggled with CSS `.active`.
- **DuckDB over SQLite**: DuckDB handles OLAP queries (GROUP BY, date_trunc, window functions) natively. Also supports Parquet read/write natively.
- **Preview-then-commit workflow**: Every import run goes through a `staged` state where the user reviews rows before they hit the ledger. The "Commit" step is a separate API call.
- **Deterministic fingerprinting**: Each transaction row gets a `transaction_fingerprint` built from hash(date + description + amount + account). This is the dedup key.
- **Background threads (not async workers)**: Normalization and category-apply jobs run in Python threads via `BackgroundTasks`. No Celery, Redis, or worker queue. The UI polls `/normalize/{job_id}` every 1500ms.
- **`_staged_runs` is persisted**: Staged run state is stored in `pipeline._staged_runs: dict[str, dict]` in memory and persisted to `data/staged/` as JSON sidecar files (BUG-2 fix).
- **YAML wizard profiles** persist column mappings per institution/account. On re-upload, the wizard auto-matches headers.
- **`source='user'` vs `source='learned'`** in `merchant_category_map`: User-assigned categories are never overwritten by the learn mechanism.

### Consistent Patterns

- All DB access goes through `get_connection(db_path)` from `db.py`.
- Every page section has a corresponding `load<PageName>()` function in `app.js` called from `navigate()`.
- Toast notifications use `toast(msg, type, duration)` — types: `'success'`, `'error'`, `'info'`.
- API calls from the frontend use the `api(method, path, body)` helper which wraps fetch and throws on non-2xx.
- Background jobs write to `normalization_jobs` for progress tracking.
- `esc(str)` is used throughout `app.js` to HTML-encode user data before inserting into innerHTML.

---

## 8. DEPENDENCIES

### Python (from `pyproject.toml`)

| Package | Version | Why it's used | Status |
|---|---|---|---|
| `duckdb` | ≥0.10.0 | Primary database engine — embedded OLAP SQL, Parquet I/O | ✅ Used |
| `pyarrow` | ≥14.0 | Required by DuckDB for Parquet read/write | ✅ Used |
| `pyyaml` | ≥6.0 | Parsing YAML mapping configs and wizard profiles | ✅ Used |
| `click` | ≥8.1 | CLI framework for `finance_etl` command group | ✅ Used |
| `chardet` | ≥5.0 | Auto-detecting CSV file encoding (UTF-8, Latin-1, etc.) | ✅ Used |
| `fastapi` | ≥0.115 | Web framework — API endpoints + static file serving | ✅ Used |
| `uvicorn` | ≥0.30 | ASGI server that runs FastAPI | ✅ Used |
| `python-multipart` | ≥0.0.9 | Required by FastAPI for `UploadFile` (CSV uploads) | ✅ Used |
| `scikit-learn` | ≥1.3 (optional) | K-Means + TF-IDF for category clustering in CLI wizard | ⚠️ CLI-only |

**Note:** `pydantic` is not listed in `pyproject.toml` but is used extensively in `api.py` for request/response models. It is a transitive dependency of FastAPI and is always available when FastAPI is installed. The code gracefully degrades (`_PYDANTIC_OK = False`) if it's somehow missing.

**Potentially removable:** `scikit-learn` is the only optional dependency. If the CLI wizard is deprecated, it can be removed from `pyproject.toml`.

### Frontend

No npm, no package.json, no build step. All frontend code is vanilla browser JS/CSS. No third-party JS libraries. No CDN dependencies.

---

## 9. VERSION TRACKING

**Current Version:** v2.5.0
**App Name:** Spendly
**Project Codename:** Ledger

### Changelog

| Version | Date | Description |
|---|---|---|
| v2.1.0 | 2026-03-10 | Initial PROJECT.md audit of rebuilt repo — identified 5 critical bugs, 8 dead code candidates |
| v2.1.1 | 2026-03-10 | Fix BUG-1: category normalization polling now calls correct `/normalize/` endpoint |
| v2.1.2 | 2026-03-10 | Fix BUG-2: staged runs now persist to `data/staged/` and survive server restarts |
| v2.1.3 | 2026-03-10 | Fix BUG-3: ui_settings now persist to `data/ui_settings.json` across restarts |
| v2.2.0 | 2026-03-10 | Quick wins: fix BUG-4 (backup restore now includes `imported_file`), fix BUG-5 (delete run deletes transactions_norm by `run_id` directly), add `imported_file` to base DDL, remove dead code (`resolve_category`, `get_unmapped_categories`, `get_category_suggestions`), remove unused config files (`rules.yaml`, `canonical_schema.yaml`) |
| v2.3.0 | 2026-03-10 | Renamed app to Spendly; sidebar version display now dynamic via `GET /version` endpoint |
| v2.3.1 | 2026-03-10 | Hardened CSV upload pipeline: encoding detection, BOM stripping, line ending normalisation, delimiter sniffing fallback, Excel magic-byte rejection, extension validation |
| v2.4.0 | 2026-03-10 | Sprint 3 — Cash Flow View: new page with income/spending/net KPIs, monthly bar chart, category breakdown, MoM delta, time filters, transfer toggle; new `GET /cashflow/summary` endpoint |
| v2.5.0 | 2026-03-10 | Sprint 4 — Smart Budget Rebalancing: suggestion engine compares avg monthly actuals vs budgets, generates over/under suggestions with editable amounts, user-confirmed apply; new `GET /budgets/rebalance` and `POST /budgets/rebalance/apply` endpoints |

### Version Increment Rules

Every commit that changes functionality MUST update this table.

Increment rules:
- Patch (v2.1.0 → v2.1.1): bug fix, style change, doc update
- Minor (v2.1.0 → v2.2.0): new feature, new endpoint, new UI section
- Major (v2.1.0 → v3.0.0): breaking schema change, full rebuild, architecture overhaul

Claude Code must add a row to the changelog on every commit that touches `src/`, `web/`, or `tests/`. Format:

| v2.1.1 | YYYY-MM-DD | \<one line description of what changed\> |

### Commit Message Rules

- Never append session URLs or session IDs to commit messages (e.g. do NOT add: `https://claude.ai/code/session_011...`)
- Commit messages must be clean, descriptive, and human-readable only
- Format: `<type>: <short description>`
- Types: `fix`, `feat`, `refactor`, `docs`, `test`, `chore`

---

## API ENDPOINT REFERENCE

All endpoints are defined in `src/finance_etl/api.py` inside `create_app()`. Interactive docs available at `http://localhost:8000/docs`.

| Method | Path | Tag | Description | Frontend Status |
|---|---|---|---|---|
| `POST` | `/upload` | files | Upload a CSV file; returns path + detected headers | 🟢 Called |
| `GET` | `/mappings` | mappings | List available YAML mapping configs | 🟡 Exists but unused by frontend |
| `POST` | `/wizard/detect` | wizard | Detect CSV headers and match against saved profiles | 🟢 Called |
| `POST` | `/wizard/validate` | wizard | Validate canonical field mapping | 🟢 Called |
| `POST` | `/wizard/save-and-run` | wizard | Save profile, start pipeline run | 🟢 Called |
| `GET` | `/wizard/profiles` | wizard | List all saved wizard profiles | 🟢 Called |
| `GET` | `/runs` | runs | List all import runs | 🟢 Called |
| `POST` | `/runs` | runs | Start a new pipeline run | 🟡 Exists but unused by frontend (wizard path used instead) |
| `GET` | `/runs/{run_id}` | runs | Get run status and counts | 🟢 Called |
| `GET` | `/runs/{run_id}/preview` | runs | Get staged rows for preview | 🟢 Called |
| `POST` | `/runs/{run_id}/commit` | runs | Commit staged run to ledger | 🟢 Called |
| `DELETE` | `/runs/{run_id}` | runs | Delete run (optionally preserve transactions) | 🟢 Called |
| `GET` | `/transactions/sources` | transactions | List available import sources per statement type | 🟢 Called |
| `GET` | `/transactions` | transactions | Query transactions with filters/grouping/sort/pagination | 🟢 Called |
| `GET` | `/transactions/totals` | transactions | Aggregate totals for filtered transactions | 🟢 Called |
| `GET` | `/transactions/unreviewed-count` | transactions | Count of all unreviewed transactions | 🟢 Called |
| `POST` | `/transactions/mark-reviewed` | transactions | Mark specific transactions as reviewed (by fingerprint) | 🟢 Called |
| `POST` | `/transactions/mark-all-reviewed` | transactions | Mark all filtered transactions as reviewed | 🟢 Called |
| `GET` | `/reports` | reports | List available analytics CSV reports | 🟢 Called |
| `GET` | `/reports/{name}` | reports | Download a report CSV | 🟢 Called |
| `POST` | `/reports/query` | reports | Run a custom parameterized report query | 🟢 Called |
| `GET` | `/charts/{name}` | reports | Get report as JSON for charting | 🟢 Called |
| `GET` | `/version` | ui | Get app version from pyproject.toml | 🟢 Called |
| `GET` | `/settings` | ui | Get current settings | 🟢 Called |
| `PATCH` | `/settings` | ui | Update settings | 🟢 Called |
| `GET` | `/logs` | ui | Get last N lines of latest log file | 🟢 Called |
| `GET` | `/logs/download` | ui | Download current log file | 🟢 Called |
| `GET` | `/metric-docs/{topic}` | ui | Inline metric documentation | 🟢 Called (opens in new tab) |
| `GET` | `/merchant-rules` | merchant | List all merchant normalization rules | 🟢 Called |
| `POST` | `/merchant-rules` | merchant | Create a merchant rule | 🟢 Called |
| `PUT` | `/merchant-rules/{id}` | merchant | Update a merchant rule | 🟢 Called |
| `DELETE` | `/merchant-rules/{id}` | merchant | Delete a merchant rule | 🟢 Called |
| `POST` | `/merchant-rules/test` | merchant | Test a rule against live descriptions | 🟢 Called |
| `GET` | `/merchant-rules/suggestions` | merchant | Suggest rules from unmatched descriptions | 🟢 Called |
| `GET` | `/merchant-categories` | merchant | List all merchant→category mappings | 🟡 Exists but unused by frontend |
| `GET` | `/merchant-categories/uncategorized` | merchant | List merchants without a category | 🟢 Called |
| `GET` | `/merchant-categories/suggestions` | merchant | Keyword-heuristic category suggestions for merchants | 🟢 Called |
| `POST` | `/merchant-categories` | merchant | Assign category to merchant | 🟢 Called |
| `DELETE` | `/merchant-categories/{merchant}` | merchant | Remove merchant category mapping | 🟡 Exists but unused by frontend |
| `POST` | `/normalize/apply` | merchant | Start batch merchant re-normalization job | 🟢 Called |
| `GET` | `/normalize/{job_id}` | merchant | Poll normalization job status | 🟢 Called (merchant); 🔴 Category uses wrong path |
| `GET` | `/category-rules` | categories | List all category rules | 🟢 Called |
| `POST` | `/category-rules` | categories | Create or update a category rule | 🟢 Called |
| `PUT` | `/category-rules/{id}` | categories | Update a category rule | 🟢 Called |
| `DELETE` | `/category-rules/{id}` | categories | Delete a category rule | 🟢 Called |
| `GET` | `/category-rules/unmapped` | categories | List unmapped raw categories with counts | 🟡 Exists but unused by frontend |
| `GET` | `/category-rules/suggestions` | categories | Suggest mappings using built-in taxonomy | 🟢 Called |
| `POST` | `/category-rules/apply` | categories | Start category normalization background job | 🟢 Called |
| `GET` | `/budgets` | budgets | List all budget goals | 🟢 Called |
| `POST` | `/budgets` | budgets | Create or update a budget goal | 🟢 Called |
| `DELETE` | `/budgets/{id}` | budgets | Delete a budget goal | 🟢 Called |
| `GET` | `/budgets/rebalance` | budgets | Analyse avg spend vs budget, generate rebalance suggestions | 🟢 Called |
| `POST` | `/budgets/rebalance/apply` | budgets | Apply user-selected budget adjustments | 🟢 Called |
| `GET` | `/dashboard/summary` | dashboard | MTD spend, top categories, budgets vs actual, recent transactions | 🟢 Called |
| `GET` | `/cashflow/summary` | cashflow | Income vs spending vs net, monthly breakdown, category breakdown, MoM delta | 🟢 Called |
| `GET` | `/recurring` | recurring | Detect recurring transactions and return patterns + monthly total | 🟢 Called |
| `POST` | `/recurring/override` | recurring | Mark or unmark a merchant as recurring (user override) | 🟢 Called |
| `DELETE` | `/recurring/override/{merchant}` | recurring | Remove a recurring override | 🟢 Called |
| `GET` | `/backup/export` | backup | Export full state as v2 JSON (all 9 tables + wizard profiles) | 🟢 Called |
| `POST` | `/backup/restore` | backup | Restore from v1 or v2 JSON backup (auto-migrates, auto-snapshots) | 🟢 Called |
| `GET` | `/backup/status` | backup | Backup system status: last export, auto-backups list, table counts | 🟢 Called |
| `GET` | `/` | ui | Serve web UI (index.html) | 🟢 Entry point |
| `GET` | `/docs` | (FastAPI auto) | Interactive API documentation | 🟢 Auto-generated |

**Frontend calls with no backend endpoint:**
| Method | Path | Called from | Issue |
|---|---|---|---|
| `GET` | `/category-normalize/{jobId}` | `app.js:3174` (`_pollCatNorm`) | 🔴 Endpoint does not exist — should be `/normalize/{jobId}` |
