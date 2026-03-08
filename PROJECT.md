# PROJECT.md — finance_etl
> Persistent memory and source of truth for all development sessions.
> **Update this file whenever features, schema, or file structure change.**

---

## 1. APP OVERVIEW

**finance_etl** is a fully local, deterministic ETL pipeline and web dashboard for importing, normalizing, categorizing, and analyzing personal bank and credit-card transaction CSVs. It runs entirely on the user's machine — no cloud, no sync, no external services. All data lives in a single DuckDB file on disk.

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
- Border radius: `8px`, Shadow: `0 1px 3px rgba(0,0,0,.08)`

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
├── conftest.py                 ← pytest shared fixtures
├── pytest.ini                  ← pytest config
├── install.sh                  ← bash installer for non-Docker usage
├── .env / .env.example         ← API host/port overrides
├── .github/workflows/
│   └── docker-publish.yml      ← publishes Docker image to registry on push
│
├── config/
│   ├── canonical_schema.yaml   ← defines canonical field names for the mapping wizard
│   ├── categories/
│   │   └── rules.yaml          ← YAML category rules file (LEGACY — superseded by DB table)
│   ├── mappings/               ← YAML bank column mapping files (used by CLI; wizard generates these)
│   │   ├── example_debit_credit.yaml
│   │   └── example_signed_amount.yaml
│   └── wizard_profiles/        ← per-institution/account YAML profiles saved by the web wizard
│       ├── testbank/
│       │   ├── amtdc01.yaml
│       │   ├── cc1234.yaml
│       │   └── chk1234.yaml
│       └── testbank_smoke/
│           └── chk_smoke001.yaml
│
├── data/                       ← runtime data (gitignored in prod; present here with test data)
│   ├── db/finance.duckdb       ← THE database — all user data lives here
│   ├── logs/                   ← per-run log files (UUID-named) + api.log
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
│   ├── api.py                  ← FastAPI app factory (create_app); ALL endpoints defined here
│   ├── analytics.py            ← Stage 9: SQL analytics queries → CSV reports
│   ├── category_rules.py       ← Category normalization engine + BUILT_IN_CATEGORY_MAP
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
│   ├── profile.py              ← Stage 2: detect encoding, delimiter, headers; write profile JSON
│   ├── validate.py             ← Stage 6: validate normalized rows; flag errors/warnings
│   ├── wizard_mapping.py       ← Wizard business logic: header inference, profile merge, YAML save
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── csv_preprocess.py   ← CSV cleaning before parsing (BOM removal, encoding fixes)
│   │   ├── csv_sniff.py        ← Delimiter and quoting auto-detection
│   │   ├── dates.py            ← Date parsing with format hint support
│   │   ├── fingerprint.py      ← Deterministic transaction_fingerprint generation
│   │   ├── hashing.py          ← File content SHA-256 hashing
│   │   ├── log.py              ← Logger factory (per-run file handlers)
│   │   ├── money.py            ← Amount string parsing → Decimal
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
│       ├── index.html          ← Single-page UI (1,060+ lines); all pages embedded
│       └── static/
│           ├── app.js          ← All UI logic (~2,980 lines); no bundler/framework
│           ├── style.css       ← All styles (~700 lines)
│           └── table_controls.js ← Reusable Import Source dropdown widget
│
└── tests/
    ├── __init__.py
    ├── conftest.py (root)      ← shared fixtures
    ├── fixtures/               ← test CSVs and golden output JSON
    │   ├── golden/
    │   │   ├── expected_norm.json
    │   │   └── signed_weird.csv
    │   ├── nonstandard_headers.csv
    │   └── standard_headers.csv
    ├── smoke_test_wizard.py    ← smoke test for wizard profile matching
    ├── test_dates.py
    ├── test_fingerprint.py
    ├── test_golden_pipeline.py
    ├── test_ingest.py
    ├── test_mapping.py
    ├── test_models.py
    ├── test_money.py
    ├── test_pipeline_api.py
    └── test_wizard_mapping.py
```

**Potentially unused / orphaned files:**
- `setup_wizard.py` (root) — standalone script that appears to duplicate `src/finance_etl/wizard/setup_wizard.py`; the web wizard has superseded both
- `config/categories/rules.yaml` — YAML category rules are no longer read by the active code path; the DB `category_rules` table is the active source
- `src/finance_etl/wizard/` — the entire wizard/ subpackage is partially superseded by `wizard_mapping.py` and the web UI wizard. `header_inference.py` and `mapping_rules.py` may be called by the CLI `wizard` command only. `category_suggestion.py` is not referenced by any active web UI code path.

---

## 4. FEATURE INVENTORY

### UI Tabs (sidebar navigation)

| Tab | Page ID | Loads on navigate | Status |
|---|---|---|---|
| 🏠 Dashboard | `#page-dashboard` | `loadDashboard()` on boot | ✅ Working |
| 📥 Import | `#page-import` | (upload is event-driven) | ✅ Working |
| 📋 History | `#page-history` | `loadHistory()` | ✅ Working |
| 💳 Credit Cards | `#page-credit-cards` | `loadTxnTab('credit_card')` | ✅ Working |
| 🏦 Bank Transactions | `#page-bank-transactions` | `loadTxnTab('bank')` | ✅ Working |
| 📊 Reports | `#page-reports` | `loadReports()` | ✅ Working |
| 🏪 Merchants | `#page-merchant-rules` | `loadMerchantRules()`, `loadUncategorized()` | ✅ Working |
| 🏷️ Categories | `#page-category-rules` | `loadCategoryRules()` | ✅ Working |
| ⚙️ Settings | `#page-settings` | `loadSettings()` | ✅ Working |

### Feature Details

**Dashboard (`#page-dashboard`)**
- MTD spend KPI card, transaction count card
- Month navigation (prev/next arrows) — `dashboardPrevMonth()`, `dashboardNextMonth()`
- Top categories bar chart (horizontal, CSS-rendered)
- Budget tracker with inline add/edit/delete form — `openBudgetForm()`, `saveBudget()`, `deleteBudget()`
- Recent transactions table (last 10)
- API: `GET /dashboard/summary?year=&month=`

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
- Sortable columns
- Infinite scroll / "Load more" (100 rows per page)
- Totals footer row
- API: `GET /transactions`, `GET /transaction-totals`, `GET /transactions/sources`

**Reports (`#page-reports`)**
- Static report cards: spend_by_month_category, cashflow_by_month, spend_by_merchant, totals_by_account, top_merchants
- Per-report: view as chart (bar, time-series), download CSV
- Chart viewer with group-by and date-from/date-to filters
- Custom Report Builder: add/remove filters, group-by, bucket (day/week/month/year), order-by, limit
- Quick date presets in custom report
- Results rendered as table with download-to-CSV button
- API: `GET /reports`, `GET /reports/{name}/download`, `GET /charts/{name}`, `POST /custom-report`, `GET /metric-docs/{topic}`

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
  - ⚠️ Was broken until recent fix (duplicate element IDs)
- Suggested Merchant Categories panel: `loadCategorySuggestions()` → `GET /merchant-categories/suggestions`
  - Keyword-heuristic matching of merchant names to categories
  - Accept assigns category to merchant via `/merchant-categories`
  - ⚠️ Accept/Dismiss buttons broken (see Known Issues §6)
- Category Normalization Rules CRUD table: `loadCategoryRules()` → `GET /category-rules`
  - Maps raw bank category → normalized category + parent group
  - Inline editor form with parent group dropdown (fixed list of 12 parents)
- Apply Normalization button: `startCategoryNormalize()` → `POST /category-rules/apply` (background job, polled)
- API: Full CRUD on `/category-rules`, `/category-rules/apply`, `/category-rules/suggestions`, `/merchant-categories/suggestions`

**Settings (`#page-settings`)**
- Verbose API error messages toggle
- Show logs panel on error toggle
- Save settings button — `PATCH /settings`
- Refresh logs button — `GET /logs`
- Download log file link — `GET /logs/download`
- Backend logs panel (pre-formatted, last 200 lines)
- **Data Backup & Restore** card:
  - Download Backup (JSON) button — `downloadBackup()` → `GET /backup/export`
  - File picker for restore — `uploadBackup()` → `POST /backup/restore`

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
| `transaction_fingerprint` | TEXT NOT NULL UNIQUE | Deterministic dedup key |
| `ingested_at` | TIMESTAMP DEFAULT NOW | When the row was loaded |
| `statement_type` | TEXT | `'credit_card'` or `'bank'` |
| `run_id` | TEXT | FK to `runs.run_id` |
| `transaction_subtype` | TEXT | `'spending'`, `'payment'`, `'adjustment'`, or NULL (bank) |
| `resolved_amount` | DECIMAL(18,2) | Always ≥ 0; direction encoded in `transaction_subtype` |
| `category_normalized` | TEXT | Normalized category from category rules (added by migration) |
| `category_parent` | TEXT | Parent group (e.g. "Food & Dining") from category rules |

**Index:** `UNIQUE INDEX idx_tx_fingerprint ON transactions_norm(transaction_fingerprint)`

**Key relationships:**
- `file_hash` → `raw_files.file_hash`
- `run_id` → `runs.run_id`
- `merchant` → `merchant_category_map.merchant` (soft, not enforced)
- `category` → `category_rules.raw_category` (soft, not enforced)

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
| `amount_debit_raw` | TEXT | Added by migration |
| `amount_credit_raw` | TEXT | Added by migration |

Rows exist only during preview phase; deleted after commit or discard. Rows may also be orphaned if the process crashes after staging but before commit/discard.

---

### `runs` — import run ledger

| Column | Type | Notes |
|---|---|---|
| `run_id` | TEXT PK | UUID |
| `started_at` | TIMESTAMP | |
| `finished_at` | TIMESTAMP | |
| `status` | TEXT | `pending`, `running`, `staged`, `committing`, `success`, `failed` |
| `statement_type` | TEXT | `'credit_card'` or `'bank'` (added by migration) |
| `run_label` | TEXT | Human-readable label (added by migration) |
| `files_count` | INTEGER | |
| `rows_in` | BIGINT | |
| `rows_staged` | BIGINT | |
| `rows_normalized` | BIGINT | |
| `rows_loaded` | BIGINT | |
| `errors_count` | INTEGER | |
| `notes` | TEXT | |
| `imported_file` | TEXT | Added by migration; filename of uploaded file |

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
| `conditions` | TEXT | JSON array of `{pattern, match_type, negate}` for compound rules |
| `logic` | TEXT DEFAULT 'AND' | `'AND'` or `'OR'` for combining conditions |

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

**Built-in taxonomy covers 80+ raw category strings** across: Food & Dining, Shopping, Travel, Transportation, Entertainment, Health & Wellness, Bills & Utilities, Financial, Education, Home, Gifts & Charity, Other.

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
| `job_id` | TEXT PK | UUID or `norm_` prefixed UUID hex |
| `status` | TEXT DEFAULT 'pending' | `'pending'`, `'running'`, `'success'`, `'fail'` / `'failed'` |
| `rows_total` | BIGINT | |
| `rows_done` | BIGINT DEFAULT 0 | |
| `error` | TEXT | Error message if failed |
| `started_at` | TEXT | ISO timestamp |
| `finished_at` | TEXT | ISO timestamp |
| `created_at` | TEXT NOT NULL | ISO timestamp |

Used by both merchant renormalization (`batch_renormalize`) and category normalization (`apply_category_rules`). Status values are inconsistent: merchant jobs use `'fail'`; category jobs use `'failed'`.

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

**BUG-1: Duplicate function names in `app.js` — Merchant Category Accept/Dismiss broken**
- `acceptCatSuggestion(idx)` is defined twice: line 2486 (merchant categories, uses `_catSuggestions`, POSTs to `/merchant-categories`) and line 2830 (category rules, uses `_catSuggestionsData`, POSTs to `/category-rules`).
- `dismissCatSuggestion(idx)` is defined twice: line 2500 and line 2852.
- In non-strict JS, the **second definition always wins** at runtime. So the "Suggested Merchant Categories" panel's ✓ and ✗ buttons call the category-rules version, which reads from the wrong data array (`_catSuggestionsData`) and POSTs to the wrong endpoint (`/category-rules`).
- **Fix needed:** Rename the merchant-category functions to `acceptMerchantCatSuggestion` / `dismissMerchantCatSuggestion` and update the HTML template in `_renderCategorySuggestions()`.

**BUG-2: `normalization_jobs` status inconsistency**
- `batch_renormalize()` in `merchant_rules.py` writes status `'fail'` on error (line 301).
- `apply_category_rules()` in `category_rules.py` writes status `'failed'` on error (line 260).
- The UI polls `/normalize/{job_id}` and checks for these status values. A mismatch could cause the UI to show an incorrect state (stuck "running" for category jobs, or wrong error display for merchant jobs).
- **Fix needed:** Standardize to `'failed'` in both places.

### Hardcoded Values & Workarounds

- **Parent group list** is hardcoded in `index.html` (the `<select id="crf-parent">` in the category rule editor, ~12 options). This list is not derived from the database or `BUILT_IN_CATEGORY_MAP` — it must be manually kept in sync.
- **Budget form** has a hardcoded parent group list (same 12 values) in the dashboard section of `index.html`. Same sync problem.
- **`_CATEGORY_HINTS`** in `merchant_rules.py` (keyword → category mapping for merchant suggestions) uses different category names than `BUILT_IN_CATEGORY_MAP` in `category_rules.py`. For example, hints use "Restaurants & Dining" while the built-in map uses "Restaurants" / "Food & Dining". This causes suggestions to produce category names that don't align with the normalized taxonomy.
- **`min_transactions = 3`** in `analyze_descriptions()` is hardcoded. No UI control.
- **Backup restore** does not restore `merchant_rules.conditions` / `logic` — the JSON-serialized compound conditions column is included in the export but the restore INSERT does not pass these fields (only `pattern`, `match_type`, `merchant`, `priority`).

### Duplicate Logic

- **Two wizard implementations:** `src/finance_etl/wizard/` subpackage (CLI) and `wizard_mapping.py` (web API) both handle header inference and profile management. They are not unified. The web wizard is the primary path; the CLI wizard is rarely used.
- **`config/categories/rules.yaml`** is an unused YAML-based category rules file. The active system is the `category_rules` DB table. This file is likely leftover from an earlier phase.
- **`setup_wizard.py` at repo root** duplicates `src/finance_etl/wizard/setup_wizard.py`. Neither is referenced by the web UI.
- **`data/profiles/*.json`** and **`data/validation/*.json`** accumulate indefinitely. There is no cleanup mechanism.
- **Two category suggestion data stores in `app.js`**: `_catSuggestions` (merchant→category, from `/merchant-categories/suggestions`) and `_catSuggestionsData` (raw_category→normalized, from `/category-rules/suggestions`). Variable names are confusingly similar, causing the duplicate-function bug.

### Schema Inconsistencies

- **`imported_file` column** exists in `runs` table (added by migration) but is not in the base DDL. It's populated during import runs but not consistently shown in the history UI.
- **`transactions_stage` is never explicitly purged** after commit. The pipeline commits rows to `transactions_norm` but does not clear `transactions_stage`. Staging rows accumulate unless the user deletes runs.
- **`category` vs `category_normalized`**: `transactions_norm.category` holds the raw bank category string; `category_normalized` holds the applied rule result. The raw `category` column is what drives the category rules system. If a transaction was imported without a bank category, `category_normalized` and `category_parent` will be NULL even after running Apply Normalization.
- **`runs.status` value `'committing'`** exists in the UI state machine but may not be written to the DB during the commit background task — the API sets `running` in `_async_runs` but the DB run record status during commit is not explicitly tracked.

### Dead / Unreferenced Code

- `src/finance_etl/wizard/category_suggestion.py` — not called from any web API endpoint. Only referenced (if at all) via the legacy CLI wizard.
- `src/finance_etl/wizard/mapping_rules.py` — same; legacy CLI only.
- `src/finance_etl/wizard/header_inference.py` — the web wizard uses `wizard_mapping.py` for inference; this module may only be used by the CLI wizard.
- `config/categories/rules.yaml` — not read by any active code path.

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

- **Single HTML file for the entire UI**: No build step, no framework, no module bundler. All 9 pages are `<section class="page">` elements toggled with CSS `.active`. This was chosen for simplicity and portability (the file is served directly by FastAPI).
- **DuckDB over SQLite**: DuckDB handles OLAP queries (GROUP BY, date_trunc, window functions) natively, which SQLite cannot do without extensions. It also supports Parquet read/write natively.
- **Preview-then-commit workflow**: Every import run goes through a `staged` state where the user reviews rows before they hit the ledger. This prevents bad data from being permanently loaded. The "Commit" step is a separate API call.
- **Deterministic fingerprinting**: Each transaction row gets a `transaction_fingerprint` built from hash(date + description + amount + account). This is the dedup key — re-importing the same CSV is safe.
- **Background threads (not async workers)**: Normalization and category-apply jobs run in Python threads via `BackgroundTasks`. There is no Celery, Redis, or worker queue. The UI polls `/normalize/{job_id}` every 1500ms.
- **YAML wizard profiles** persist column mappings per institution/account. On re-upload, the wizard auto-matches headers against existing profiles and pre-fills the field selectors.
- **`source='user'` vs `source='learned'`** in `merchant_category_map`: User-assigned categories are never overwritten by the learn mechanism. Learned associations (from transaction data) are lower priority.

### Consistent Patterns

- All DB access goes through `get_connection(db_path)` from `db.py`. The `db_path` is threaded through `create_app()` as a closure variable.
- Every page section has a corresponding `load<PageName>()` function in `app.js` called from `navigate()`.
- Toast notifications use `toast(msg, type, duration)` — types: `'success'`, `'error'`, `'info'`.
- API calls from the frontend use the `api(method, path, body)` helper which wraps fetch and throws on non-2xx.
- Background jobs always write to `normalization_jobs` for progress tracking.
- `esc(str)` is used throughout `app.js` to HTML-encode user data before inserting into innerHTML.

---

## 8. DEPENDENCIES

### Python (from `pyproject.toml`)

| Package | Version | Why it's used |
|---|---|---|
| `duckdb` | ≥0.10.0 | Primary database engine — embedded OLAP SQL, Parquet I/O |
| `pyarrow` | ≥14.0 | Required by DuckDB for Parquet read/write |
| `pyyaml` | ≥6.0 | Parsing YAML mapping configs and wizard profiles |
| `click` | ≥8.1 | CLI framework for `finance_etl` command group |
| `chardet` | ≥5.0 | Auto-detecting CSV file encoding (UTF-8, Latin-1, etc.) |
| `fastapi` | ≥0.115 | Web framework — API endpoints + static file serving |
| `uvicorn` | ≥0.30 | ASGI server that runs FastAPI |
| `python-multipart` | ≥0.0.9 | Required by FastAPI for `UploadFile` (CSV uploads) |
| `scikit-learn` | ≥1.3 (optional) | K-Means + TF-IDF for category clustering in wizard. Install with `pip install -e ".[wizard]"` |

**Potentially removable:** `scikit-learn` is the only optional dependency. If the CLI wizard is deprecated, this can be removed from `pyproject.toml` entirely.

### Frontend

No npm, no package.json, no build step. All frontend code is vanilla browser JS/CSS. No third-party JS libraries. No CDN dependencies.

---

## API ENDPOINT REFERENCE

All endpoints are defined in `src/finance_etl/api.py` inside `create_app()`. Interactive docs available at `http://localhost:8000/docs`.

| Method | Path | Tag | Description |
|---|---|---|---|
| `POST` | `/upload` | files | Upload a CSV file; returns path + detected headers |
| `GET` | `/mappings` | mappings | List available YAML mapping configs |
| `POST` | `/wizard/detect` | wizard | Detect CSV headers and match against saved profiles |
| `POST` | `/wizard/validate` | wizard | Validate canonical field mapping |
| `POST` | `/wizard/save-and-run` | wizard | Save profile, start pipeline run |
| `GET` | `/wizard/profiles` | wizard | List all saved wizard profiles |
| `GET` | `/runs` | runs | List all import runs |
| `POST` | `/runs` | runs | Start a new pipeline run |
| `GET` | `/runs/{run_id}` | runs | Get run status and counts |
| `GET` | `/runs/{run_id}/preview` | runs | Get staged rows for preview |
| `POST` | `/runs/{run_id}/commit` | runs | Commit staged run to ledger |
| `DELETE` | `/runs/{run_id}` | runs | Delete run (optionally preserve transactions) |
| `GET` | `/transactions/sources` | transactions | List available import sources per statement type |
| `GET` | `/transactions` | transactions | Query transactions with filters/grouping/sort/pagination |
| `GET` | `/transaction-totals` | transactions | Aggregate totals for filtered transactions |
| `GET` | `/reports` | reports | List available analytics CSV reports |
| `GET` | `/reports/{name}/download` | reports | Download a report CSV |
| `POST` | `/custom-report` | reports | Run a custom SQL report query |
| `GET` | `/charts/{name}` | reports | Get report as JSON for charting |
| `GET` | `/settings` | settings | Get current settings |
| `PATCH` | `/settings` | settings | Update settings |
| `GET` | `/logs` | settings | Get last N lines of latest log file |
| `GET` | `/logs/download` | settings | Download current log file |
| `GET` | `/metric-docs/{topic}` | ui | Inline metric documentation |
| `GET` | `/merchant-rules` | merchant | List all merchant normalization rules |
| `POST` | `/merchant-rules` | merchant | Create a merchant rule |
| `PUT` | `/merchant-rules/{id}` | merchant | Update a merchant rule |
| `DELETE` | `/merchant-rules/{id}` | merchant | Delete a merchant rule |
| `POST` | `/merchant-rules/test` | merchant | Test a rule against live descriptions |
| `GET` | `/merchant-rules/suggestions` | merchant | Suggest rules from unmatched descriptions |
| `GET` | `/merchant-categories` | merchant | List all merchant→category mappings |
| `GET` | `/merchant-categories/uncategorized` | merchant | List merchants without a category |
| `GET` | `/merchant-categories/suggestions` | merchant | Keyword-heuristic category suggestions for merchants |
| `POST` | `/merchant-categories` | merchant | Assign category to merchant |
| `DELETE` | `/merchant-categories/{merchant}` | merchant | Remove merchant category mapping |
| `POST` | `/normalize/apply` | merchant | Start batch merchant re-normalization job |
| `GET` | `/normalize/{job_id}` | merchant | Poll normalization job status |
| `GET` | `/category-rules` | categories | List all category rules |
| `POST` | `/category-rules` | categories | Create or update a category rule |
| `PUT` | `/category-rules/{id}` | categories | Update a category rule |
| `DELETE` | `/category-rules/{id}` | categories | Delete a category rule |
| `GET` | `/category-rules/unmapped` | categories | List unmapped raw categories with counts |
| `GET` | `/category-rules/suggestions` | categories | Suggest mappings using built-in taxonomy |
| `POST` | `/category-rules/apply` | categories | Start category normalization background job |
| `GET` | `/budgets` | budgets | List all budget goals |
| `POST` | `/budgets` | budgets | Create or update a budget goal |
| `DELETE` | `/budgets/{id}` | budgets | Delete a budget goal |
| `GET` | `/dashboard/summary` | dashboard | MTD spend, top categories, budgets vs actual, recent transactions |
| `GET` | `/backup/export` | backup | Export all data as JSON (file download) |
| `POST` | `/backup/restore` | backup | Restore from a JSON backup file |
| `GET` | `/` | ui | Serve web UI (index.html) |
| `GET` | `/docs` | (FastAPI auto) | Interactive API documentation |
