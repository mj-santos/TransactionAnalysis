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
| Fuzzy matching | rapidfuzz | ≥3.0 — token sort ratio for description drift duplicate detection |
| ML (optional) | scikit-learn | ≥1.3 — install with `pip install -e ".[wizard]"` for K-Means category clustering. CLI wizard only. |
| UI stack | Vanilla HTML/CSS/JS | No framework. Single HTML file + 2 JS files + 1 CSS file. |
| Containerization | Docker + docker-compose | Python 3.12-slim base; data volume at `/app/data` |
| Packaging | setuptools (pyproject.toml) | Installable as `finance_etl` package; entry point: `finance_etl.cli:main` |
| Testing | pytest | Config in `pyproject.toml`; tests in `tests/` |

**Design system (CSS variables in `style.css`):**
- Sidebar: `#0f172a` (dark navy), 220px wide
- Primary blue: `#3b82f6`, hover `#2563eb`
- Success: `#22c55e`, Danger: `#ef4444`, Warning: `#f59e0b`, Staged: `#8b5cf6`
- Font: system-ui stack (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`)
- Border radius: `8px`, Shadow: `0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06)`
- **Dark mode**: `[data-theme="dark"]` overrides on `<html>` — toggled via sidebar footer, persisted in localStorage
- **Colorblind palette**: `[data-palette="colorblind"]` — deuteranopia/protanopia-safe; toggled via sidebar footer, persisted in localStorage

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
├── conftest.py                 ← pytest path fix: inserts src/ into sys.path
├── install.sh                  ← bash installer (curl|bash safe; main() wrapper; bash 3.2 compat)
├── .env / .env.example         ← API host/port overrides
├── .github/workflows/
│   └── docker-publish.yml      ← publishes Docker image to registry on push
│
├── config/
│   └── mappings/               ← YAML bank column mapping files (wizard generates these)
│       ├── example_debit_credit.yaml
│       └── example_signed_amount.yaml
│
├── data/                       ← runtime data (gitignored in prod)
│   ├── auto_backups/           ← auto-backup JSON files (max 5, rotated)
│   ├── db/finance.duckdb       ← THE database — all user data lives here
│   ├── logs/                   ← per-run log files (UUID-named) + api.log
│   ├── master/                 ← Parquet snapshot exports (Hive-partitioned)
│   ├── profiles/               ← per-file JSON profiling results
│   ├── raw/                    ← copies of uploaded CSVs stored by run timestamp
│   ├── reports/                ← CSV analytics exports (regenerated after each run)
│   ├── staged/                 ← staged run JSON sidecar files (survive restarts)
│   ├── uploads/                ← uploaded files (short-lived)
│   └── validation/             ← per-run validation JSON reports
│
├── docs/
│   ├── architecture.md
│   ├── CONFIG.md
│   ├── DEVELOPMENT.md
│   ├── INSTALL.md
│   ├── USER_GUIDE.md
│   ├── NEXT_PHASE_READINESS.md
│   ├── config_examples.md
│   ├── dependency_entrypoint_map.md
│   └── refactor_plan.md
│
├── src/finance_etl/            ← main Python package
│   ├── __init__.py
│   ├── accounts/               ← Accounts & Liabilities subpackage
│   │   ├── __init__.py         ← FastAPI sub-router
│   │   ├── balance_ops.py      ← Bulk update, ledger, stale detection, snapshots
│   │   ├── crud.py             ← Account CRUD + CoA auto-assignment
│   │   ├── db_migrations.py    ← ALTER TABLE + CREATE TABLE migrations
│   │   ├── routes.py           ← API route handlers
│   │   └── schemas.py          ← Pydantic models (request/response)
│   ├── api.py                  ← FastAPI app factory; ALL endpoints
│   ├── analytics.py            ← Stage 9: SQL analytics → CSV reports
│   ├── backup_migrations.py    ← Backup payload migration chain (v1→v2)
│   ├── category_rules.py       ← Category normalization engine + BUILT_IN_CATEGORY_MAP (~97 entries)
│   ├── cli.py                  ← Click CLI: run, ingest, validate, parquet, analytics, api, wizard
│   ├── db.py                   ← DuckDB connection factory + DDL + migrations
│   ├── ingest.py               ← Stage 1-2: file registration, run creation, raw copy
│   ├── load.py                 ← Stage 7: insert normalized rows into transactions_norm
│   ├── mapping.py              ← Stage 3-4: load YAML mapping, map CSV rows → stage rows
│   ├── merchant_rules.py       ← Merchant normalization engine + category suggestions
│   ├── models.py               ← Typed dataclasses: MappingConfig, DateConfig, AmountConfig
│   ├── normalize.py            ← Stage 5: normalize staged rows
│   ├── parquet.py              ← Stage 8: export → partitioned Parquet
│   ├── pipeline.py             ← Orchestrator: run_with_options(), commit_run(), RunResult
│   ├── recurring.py            ← Recurring transaction detection engine
│   ├── profile.py              ← Stage 2: detect encoding, delimiter, headers
│   ├── validate.py             ← Stage 6: validate normalized rows
│   ├── wizard_mapping.py       ← Wizard business logic: header inference, profile merge, YAML save
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── csv_preprocess.py   ← CSV cleaning (BOM, encoding, header strip)
│   │   ├── csv_sniff.py        ← Delimiter and quoting auto-detection
│   │   ├── dates.py            ← Date parsing with format hint support
│   │   ├── fingerprint.py      ← Deterministic transaction_fingerprint (SHA-256)
│   │   ├── hashing.py          ← File content SHA-256 hashing
│   │   ├── log.py              ← Logger factory (per-run file handlers)
│   │   ├── money.py            ← Amount string parsing → Decimal
│   │   ├── fuzzy_dedup.py      ← Post-import fuzzy duplicate detection (rapidfuzz)
│   │   ├── query_helpers.py    ← INCOME_FILTER constant, evaluate_rule_groups()
│   │   └── text.py             ← Text normalization utilities
│   │
│   ├── wizard/                 ← CLI wizard (superseded by web wizard for most users)
│   │   ├── __init__.py
│   │   ├── category_suggestion.py
│   │   ├── header_inference.py
│   │   ├── mapping_rules.py
│   │   └── setup_wizard.py
│   │
│   └── web/
│       ├── index.html          ← Single-page UI; all pages as hidden sections
│       └── static/
│           ├── accounts.js     ← Accounts & Liabilities UI logic
│           ├── app.js          ← All UI logic; no bundler/framework
│           ├── style.css       ← All styles
│           └── table_controls.js ← Reusable widgets: makeSourceDropdown(), renderTxnTotals()
│
└── tests/
    ├── __init__.py
    ├── fixtures/               ← test CSVs and golden output JSON
    └── test_*.py               ← 362+ tests covering all features
```

**Potentially unused / orphaned files:**
- `setup_wizard.py` (repo root) — standalone script duplicating CLI wizard; web wizard supersedes both
- `pytest.ini` — duplicates `[tool.pytest.ini_options]` in `pyproject.toml`

---

## 4. FEATURE INVENTORY

### UI Tabs (sidebar navigation)

| Tab | Page ID | Load function | Status |
|---|---|---|---|
| Dashboard | `#page-dashboard` | `loadDashboard()` | ✅ |
| Import | `#page-import` | (event-driven) | ✅ |
| History | `#page-history` | `loadHistory()` | ✅ |
| Credit Cards | `#page-credit-cards` | `loadTxnTab('credit_card')` | ✅ |
| Bank Transactions | `#page-bank-transactions` | `loadTxnTab('bank')` | ✅ |
| Cash Flow | `#page-cashflow` | `loadCashFlow()` | ✅ |
| Reports | `#page-reports` | `loadReports()` | ✅ |
| Merchants | `#page-merchant-rules` | `loadMerchantRules()` | ✅ |
| Categories | `#page-category-rules` | `loadCategoryRules()` | ✅ |
| Recurring | `#page-recurring-transactions` | `loadRecurringTransactions()` | ✅ |
| Accounts | `#page-accounts` | `loadAccounts()` | ✅ Phase 1+2 |
| Utilities | `#page-utilities` | `loadUtilCategories()` + others | ✅ |
| Settings | `#page-settings` | `loadSettings()` | ✅ |

### Global Features

- **Global Transaction Search**: persistent topbar search; text + amount operators (`>50`, `<200`, `50-100`); keyboard nav; `/` shortcut
- **Keyboard Shortcuts**: `j`/`k` navigate, `r` review, `c` category edit, `x` toggle select, `/` search, `?` help, `1`-`9` tabs
- **Dark/Light Mode Toggle**: sidebar footer, persisted in localStorage
- **Colorblind Palette Toggle**: sidebar footer, persisted in localStorage
- **Onboarding Flow**: 3-step modal for first-time users

### Feature Details

**Dashboard** — MTD spend KPI, transaction count, unreviewed count; month navigation; top categories (clickable drill-down); budget tracker with rebalance; spending alerts (80%/100%); savings goals; monthly summary; net worth widget; year-in-review; recent transactions.

**Import** — Drag-and-drop CSV upload; auto-triggered 3-step Mapping Wizard (detects headers, dates, amount style, statement type); profile matching for instant re-import; staged preview; commit/discard; post-commit duplicate detection.

**History** — Run list with status badges; per-run preview/commit/delete (with option to preserve transactions).

**Credit Cards / Bank Transactions** — Identical feature set per tab: date/description/merchant/category/account/year filters; quick date presets; group-by; unreviewed toggle; sortable columns; infinite scroll; totals footer (CC: Spending/Payments/Adjustments/Net Activity; Bank: Income/Outflow/Net); Card Financial Summary (CC only); per-row mark reviewed, inline category edit (override-protected), notes, split, tags; bulk actions (assign category/merchant, mark reviewed, exclude, tag).

**Cash Flow** — Income/Spending/Net KPIs; MoM delta; time period filters with custom range; transfer toggle; monthly bar chart; category breakdown (clickable drill-down).

**Reports** — 5 standard analytics reports with charts and CSV downloads; custom report builder with filters/group-by/bucket/order-by/limit.

**Merchants** — Intelligence panel (spend, trends, frequency, acceleration, date range presets); recommended rules (fuzzy grouping, low-frequency, persistent dismissals, auto-fill unmatched); CRUD rules table with search and compound conditions; re-normalize button; collapsible panels.

**Categories** — Suggested mappings + suggested merchant categories (subcategory-aware, persistent dismissals); CRUD rules table with grouped condition builder and inline search; apply normalization (background job).

**Recurring** — Auto-detection (3+ occurrences, interval/amount CV thresholds); frequency classification; monthly cost KPI; per-row edit/pause/delete; paused section; annual fee suggestions (keyword-based, accept/edit/dismiss/view dismissed/deleted); date editing; overrides in DB; backup/restore support.

**Utilities** — Sidebar badge for pending duplicates; 5 sections: category list (searchable taxonomy), merchant list (sortable, inline category edit, bulk actions), rule tester (classification trace), duplicate review (side-by-side with resolve actions), data health (5 metrics with nav links and Fix Now).

**Settings** — Verbose logs + show logs toggles (persisted to `data/ui_settings.json`); logs panel; backup/restore v2 (export/restore with progress bars, auto-backup on commit, v1→v2 migration); tag management (CRUD with colors, per-tag totals).

---

## 5. DATA MODELS & SCHEMA

All tables live in `data/db/finance.duckdb`. Schema bootstrapped and migrated in `db.py`.

### `transactions_norm` — the ledger

| Column | Type | Notes |
|---|---|---|
| `transaction_date` | DATE NOT NULL | Parsed date |
| `posted_date` | DATE | Optional posting date |
| `description` | TEXT NOT NULL | Raw description from CSV |
| `merchant` | TEXT | Normalized merchant name |
| `category` | TEXT | Raw bank category from CSV |
| `amount` | DECIMAL(18,2) NOT NULL | Signed amount |
| `currency` | TEXT DEFAULT 'USD' | |
| `bank_name` | TEXT NOT NULL | From mapping |
| `account_name` | TEXT NOT NULL | From mapping |
| `account_id` | TEXT NOT NULL | From mapping |
| `source_file` | TEXT NOT NULL | Original filename |
| `source_row` | INTEGER NOT NULL | Row in CSV |
| `file_hash` | TEXT NOT NULL | SHA-256 of source file |
| `transaction_fingerprint` | TEXT NOT NULL | Dedup key (UNIQUE INDEX) |
| `ingested_at` | TIMESTAMP DEFAULT NOW | |
| `statement_type` | TEXT | `'credit_card'` or `'bank'` |
| `run_id` | TEXT | FK to `runs` |
| `transaction_subtype` | TEXT | `'spending'`/`'payment'`/`'adjustment'`/NULL |
| `resolved_amount` | DECIMAL(18,2) | Always ≥ 0 |
| `category_normalized` | TEXT | From category rules |
| `category_parent` | TEXT | Parent group |
| `unreviewed` | BOOLEAN DEFAULT TRUE | |
| `notes` | TEXT | User note |
| `is_split` | BOOLEAN DEFAULT FALSE | Split parent (excluded from totals) |
| `split_parent_fingerprint` | TEXT | FK to parent fingerprint |
| `category_override` | BOOLEAN DEFAULT FALSE | Skip during normalization |
| `excluded` | BOOLEAN DEFAULT FALSE | Hidden from queries |

**Fingerprint:** `SHA-256(bank_name | account_id | date(ISO) | UPPER(description) | amount(.2f) | currency)`

### Other tables

| Table | Purpose |
|---|---|
| `transactions_stage` | Temporary staging for preview-before-commit |
| `runs` | Import run ledger (status, counts) |
| `raw_files` | Uploaded file registry (hash, encoding, delimiter) |
| `merchant_rules` | Merchant normalization rules (grouped boolean conditions) |
| `merchant_category_map` | Merchant → category (user vs learned source) |
| `category_rules` | Raw bank category → normalized + parent |
| `budget_goals` | Monthly budget targets per category |
| `normalization_jobs` | Background job tracking |
| `duplicate_candidates` | Near-duplicate detection results |
| `recurring_overrides` | User recurring mark/unmark/pause/edit |
| `recurring_dismissals` | Dismissed annual fee suggestions |
| `category_dismissals` | Dismissed category suggestions |
| `rule_dismissals` | Dismissed rule suggestions |
| `tags` | User-defined tags (name + color) |
| `transaction_tags` | Many-to-many tag assignments |
| `savings_goals` | Savings targets with progress |
| `monthly_summaries` | Stored monthly reports |
| `nw_accounts` | Net worth account balances (extended with CoA, Plaid-aligned fields) |
| `nw_snapshots` | Point-in-time net worth snapshots |
| `annual_reports` | Stored annual reports |
| `schema_version` | Schema version tracking |
| `ap_balance_ledger` | Immutable balance history (append-only) |
| `ap_billing_cycles` | Statement tracking per account |
| `ap_payments` | Double-entry payment log |
| `ap_payment_plan` | Monthly payment assignment matrix |
| `ap_payment_source_tags` | Short code → account lookup |
| `ap_card_benefits` | Credit card perks tracking |
| `ap_apr_terms` | APR tracking per account |

---

## 6. KNOWN ISSUES & TECH DEBT

### Open Bugs

| ID | Severity | Summary |
|---|---|---|
| BUG-20 | Low | Dark mode `.run-status-success` selectors never match (should be `.run-status.success`) |
| BUG-23 | High | `dupes_skipped` count computed but never shown to user |
| BUG-24 | High | No date range overlap warning during import |
| BUG-25 | Medium | Import preview doesn't flag duplicate rows |
| BUG-26 | Medium | `file_hash` check in `register_files()` is audit-only, not a gate |
| BUG-27 | Medium | Failed imports leave orphaned staging/raw_files rows |
| BUG-28 | Low | Duplicate detection only runs post-commit, not during preview |

### Tech Debt

- **Hardcoded parent groups** in `index.html` `<select id="crf-parent">` (12 options) — not derived from taxonomy
- **Two wizard implementations**: `wizard/` subpackage (CLI) and `wizard_mapping.py` (web) not unified
- `setup_wizard.py` at repo root duplicates CLI wizard
- `data/profiles/*.json` and `data/validation/*.json` accumulate without cleanup
- `raw_files` excluded from `_BACKUP_TABLES` — lost on restore
- `runs.notes` in DDL but never written; `schema_version.version` never incremented
- Bulk tag assignment still uses `prompt()` instead of proper picker
- Grouped mode category edit disabled (the `&& fp` guard skips aggregated rows)
- Dead code: `addConditionRow()`, `deleteBudget()` in app.js; `POST /wizard/validate`, `GET /wizard/profiles` unused endpoints; `sha256_str()`, `get_canonical_fields_for_type()` in Python
- Tracked `.DS_Store` and `.env` files should be untracked

### Recommended Future Work

**Priority 1 — Data integrity:** Surface `dupes_skipped` in UI (BUG-23); date range overlap warning (BUG-24); duplicate flagging in preview (BUG-25); pre-commit duplicate detection (BUG-28).

**Priority 2 — UX:** Fix dark mode badge selectors (BUG-20); make file_hash check meaningful or remove (BUG-26).

**Priority 3 — Cleanup:** Orphaned staging cleanup (BUG-27); unify wizard implementations; include `raw_files` in backup.

---

## 7. DECISIONS & CONVENTIONS

### Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Python modules | `snake_case` | `merchant_rules.py` |
| Python functions | `snake_case` | `load_rules()` |
| Python classes | `PascalCase` | `CompiledRule` |
| JS functions | `camelCase` | `loadMerchantRules()` |
| JS private | `_camelCase` | `_renderCatSuggestions()` |
| HTML IDs | `kebab-case` | `cat-suggest-status` |
| CSS variables | `--kebab-case` | `--sidebar-bg` |
| API routes | `kebab-case` | `/merchant-rules` |
| DB tables | `snake_case` | `transactions_norm` |

### Architectural Decisions

- **Single HTML file**: No build step, no framework. All pages as `<section class="page">` toggled with CSS `.active`.
- **DuckDB**: OLAP queries + Parquet natively. Single-writer constraint → all connections use `try/finally`.
- **Preview-then-commit**: Every import goes through `staged` state before hitting the ledger.
- **Deterministic fingerprinting**: SHA-256(date + description + amount + account). Primary dedup.
- **Background threads**: Normalization via `BackgroundTasks`. UI polls `/normalize/{job_id}` every 1500ms.
- **Staged runs persistence**: JSON sidecar files in `data/staged/` survive server restart.
- **Wizard profiles**: YAML per institution/account. Auto-matches on re-upload.
- **`category_override`**: Manual edits set flag; normalization skips flagged rows.
- **`INCOME_FILTER`**: `amount > 0 AND statement_type = 'bank'`. CC positive amounts never income.
- **Four-layer dedup**: (1) File hash (audit), (2) Fingerprint UNIQUE index (primary), (3) Near-duplicate detection (post-commit), (4) Fuzzy duplicate detection (post-commit, rapidfuzz).
- **Grouped boolean rules**: 1+ condition groups (inter-group AND, intra-group AND|OR). Shared `evaluate_rule_groups()`.
- **Backup column policy**: `_TABLE_COLUMNS` explicit list for `transactions_norm`; other tables use `SELECT *`.

### Consistent Patterns

- DB access: `get_connection(db_path)` from `db.py`
- Page loading: `load<PageName>()` called from `navigate()`
- Toasts: `toast(msg, type, duration)` — `'success'`, `'error'`, `'info'`
- API calls: `api(method, path, body)` helper
- HTML encoding: `esc(str)` throughout `app.js`
- Collapsible panels: `.card-header-toggle` + `.card-collapsible-body`, localStorage state
- Category drill-down: `openCategoryDrilldown(categoryParent, dateFrom, dateTo)`
- Tab routing: `resolveTransactionTab(transactions)` derives CC/Bank from data
- Category picker: `openCategoryPicker(targetElement, options)` — single shared component

---

## 8. DEPENDENCIES

### Python (from `pyproject.toml`)

| Package | Version | Purpose |
|---|---|---|
| `duckdb` | ≥0.10.0 | Primary database |
| `pyarrow` | ≥14.0 | Parquet I/O |
| `pyyaml` | ≥6.0 | YAML config |
| `click` | ≥8.1 | CLI |
| `chardet` | ≥5.0 | CSV encoding detection |
| `fastapi` | ≥0.115 | Web framework |
| `uvicorn` | ≥0.30 | ASGI server |
| `python-multipart` | ≥0.0.9 | File uploads |
| `rapidfuzz` | ≥3.0 | Fuzzy duplicate detection |
| `scikit-learn` | ≥1.3 (optional) | CLI wizard clustering |

**Note:** `pydantic` is a transitive dependency of FastAPI, used in `api.py` for request/response models.

### Frontend

No npm, no package.json, no build step. Vanilla browser JS/CSS only. No third-party libraries.

---

## 9. VERSION TRACKING

**Current Version:** v2.37.0
**App Name:** Spendly

### Changelog

| Version | Date | Description |
|---|---|---|
| v2.37.0 | 2026-03-16 | feat: Accounts Phase 2 — balance ledger, overview KPIs, bulk update, stale detection |
| v2.36.0 | 2026-03-16 | feat: Accounts & Liabilities module Phase 1 (schema + CRUD + UI) |
| v2.35.2 | 2026-03-13 | fix: bulk category override + remove dead health metric |
| v2.35.1 | 2026-03-13 | fix: bulk category assignment DOM cleanup + missing SELECT columns |
| v2.35.0 | 2026-03-13 | feat: recurring charges date editing + suggestion dismissal |
| v2.34.0 | 2026-03-13 | refactor: merge uncategorized merchants into Data Health |
| v2.33.0 | 2026-03-12 | fix: backup/restore dismissal tables + data health navigation |
| v2.32.0 | 2026-03-12 | feat: UX polish — bulk category picker, export progress bar, search |
| v2.31.0 | 2026-03-12 | feat: subcategory matching + persistent dismissals |
| v2.30.0 | 2026-03-12 | feat: recurring dropdown actions + paused section |
| v2.29.1 | 2026-03-12 | fix: annual fee suggestion accept/edit UI |
| v2.29.0 | 2026-03-12 | feat: fuzzy merchant grouping + auto-fill unmatched |
| v2.28.0 | 2026-03-12 | feat: annual membership fee detection |
| v2.27.1 | 2026-03-12 | feat: backup restore progress bar |
| v2.27.0 | 2026-03-12 | feat: Merchant Intelligence date pickers |
| v2.26.4 | 2026-03-12 | fix: orphan categories Fix Now |
| v2.26.3 | 2026-03-12 | fix: amount variance UX in duplicate review |
| v2.26.2 | 2026-03-12 | fix: fuzzy duplicate detection for description drift |
| v2.26.1 | 2026-03-11 | fix: consolidate category pickers |
| v2.26.0 | 2026-03-11 | feat: wire split transaction UI |
| v2.25.3 | 2026-03-11 | fix: add excluded column |
| v2.25.2 | 2026-03-11 | fix: batch_renormalize skips category_override |
| v2.25.1 | 2026-03-10 | Audit 1 — codebase reality check |
| v2.25.0 | 2026-03-10 | Merchant List category edit rewrite |
| v2.24.2 | 2026-03-10 | fix: tab routing via resolveTransactionTab |
| v2.24.1 | 2026-03-10 | fix: dynamic sidebar version |
| v2.24.0 | 2026-03-10 | feat: category override + shared picker |
| v2.23.2 | 2026-03-10 | fix: backup explicit column list |
| v2.23.1 | 2026-03-10 | fix: replace SQLite changes() with DuckDB patterns |
| v2.23.0 | 2026-03-10 | fix: restore modal + filters + dark mode |
| v2.22.0 | 2026-03-10 | fix: bulk actions + assign merchant |
| v2.21.0 | 2026-03-10 | feat: category edit + rule test + retention |
| v2.20.0 | 2026-03-10 | feat: rule search + grouped conditions |
| v2.19.0 | 2026-03-10 | feat: year filter + drill-down |
| v2.18.1 | 2026-03-10 | fix: dashboard loading + reports after restore |
| v2.18.0 | 2026-03-10 | feat: merchant rule grouped boolean logic |
| v2.17.3 | 2026-03-10 | fix: Docker build cache |
| v2.17.2 | 2026-03-10 | fix: utilities category column names |
| v2.17.1 | 2026-03-10 | fix: restore connection conflict |
| v2.17.0 | 2026-03-10 | feat: duplicate detection + utilities tab |
| v2.16.0 | 2026-03-10 | feat: notes + split transactions |
| v2.15.0 | 2026-03-10 | feat: global search + dashboard drill-down |
| v2.14.0 | 2026-03-10 | feat: collapsible panels |
| v2.13.2 | 2026-03-10 | fix: centralized INCOME_FILTER |
| v2.13.1 | 2026-03-10 | fix: income classification |
| v2.13.0 | 2026-03-10 | feat: keyboard shortcuts + dark mode + onboarding |
| v2.12.0 | 2026-03-10 | feat: Year-in-Review reports |
| v2.11.0 | 2026-03-10 | feat: Net Worth snapshots |
| v2.10.0 | 2026-03-10 | feat: spending alerts |
| v2.9.0 | 2026-03-10 | feat: Merchant Intelligence |
| v2.8.0 | 2026-03-10 | feat: Monthly Summary engine |
| v2.7.0 | 2026-03-10 | feat: Savings Goals |
| v2.6.0 | 2026-03-10 | feat: transaction tagging |
| v2.5.0 | 2026-03-10 | feat: budget rebalancing |
| v2.4.0 | 2026-03-10 | feat: Cash Flow view |
| v2.3.1 | 2026-03-10 | fix: CSV upload hardening |
| v2.3.0 | 2026-03-10 | feat: renamed to Spendly |
| v2.2.0 | 2026-03-10 | fix: backup restore + dead code removal |
| v2.1.3 | 2026-03-10 | fix: settings persistence |
| v2.1.2 | 2026-03-10 | fix: staged runs persistence |
| v2.1.1 | 2026-03-10 | fix: category normalization polling |
| v2.1.0 | 2026-03-10 | Initial PROJECT.md audit |

### Version Increment Rules

Every commit that changes functionality MUST update this table.

- Patch: bug fix, style change, doc update
- Minor: new feature, new endpoint, new UI section
- Major: breaking schema change, architecture overhaul

**pyproject.toml `version` MUST be incremented on every commit that touches `src/`, `web/`, or `tests/`.** The sidebar reads from `GET /version` → `importlib.metadata.version("finance_etl")`.

### Commit Message Rules

- Never append session URLs or session IDs to commit messages
- Commit messages must be clean, descriptive, and human-readable only
- Format: `<type>: <short description>`
- Types: `fix`, `feat`, `refactor`, `docs`, `test`, `chore`

---

## API ENDPOINT REFERENCE

All endpoints in `src/finance_etl/api.py` inside `create_app()`. Interactive docs at `http://localhost:8000/docs`.

| Method | Path | Description | Status |
|---|---|---|---|
| `POST` | `/upload` | Upload CSV file | 🟢 |
| `POST` | `/wizard/detect` | Detect headers + match profiles | 🟢 |
| `POST` | `/wizard/validate` | Validate field mapping | 🟡 Unused |
| `POST` | `/wizard/save-and-run` | Save profile + start import | 🟢 |
| `GET` | `/wizard/profiles` | List saved profiles | 🟡 Unused |
| `GET` | `/mappings` | List YAML mappings | 🟡 Unused |
| `GET` | `/runs` | List import runs | 🟢 |
| `POST` | `/runs` | Start pipeline run | 🟡 Unused |
| `GET` | `/runs/{run_id}` | Run status + counts | 🟢 |
| `GET` | `/runs/{run_id}/preview` | Staged rows preview | 🟢 |
| `POST` | `/runs/{run_id}/commit` | Commit to ledger | 🟢 |
| `DELETE` | `/runs/{run_id}` | Delete run | 🟢 |
| `GET` | `/transactions` | Query with filters | 🟢 |
| `GET` | `/transactions/search` | Global search | 🟢 |
| `GET` | `/transactions/totals` | Aggregate totals | 🟢 |
| `GET` | `/transactions/unreviewed-count` | Unreviewed count | 🟢 |
| `GET` | `/transactions/years` | Distinct years | 🟢 |
| `GET` | `/transactions/sources` | Import sources | 🟢 |
| `POST` | `/transactions/mark-reviewed` | Mark reviewed | 🟢 |
| `POST` | `/transactions/mark-all-reviewed` | Mark all reviewed | 🟢 |
| `PATCH` | `/transactions/{fingerprint}` | Update fields | 🟢 |
| `PATCH` | `/transactions/bulk-assign-merchant` | Bulk assign merchant | 🟢 |
| `POST` | `/transactions/{fingerprint}/split` | Split transaction | 🟢 |
| `DELETE` | `/transactions/{fingerprint}/split` | Unsplit | 🟢 |
| `GET` | `/merchants/search` | Merchant type-ahead | 🟢 |
| `GET` | `/merchant-rules` | List rules | 🟢 |
| `POST` | `/merchant-rules` | Create rule | 🟢 |
| `PUT` | `/merchant-rules/{id}` | Update rule | 🟢 |
| `DELETE` | `/merchant-rules/{id}` | Delete rule | 🟢 |
| `POST` | `/merchant-rules/test` | Test rule | 🟢 |
| `GET` | `/merchant-rules/suggestions` | Suggest rules | 🟢 |
| `POST` | `/merchant-rules/suggestions/{pattern}/dismiss` | Dismiss | 🟢 |
| `DELETE` | `/merchant-rules/suggestions/{pattern}/dismiss` | Undo dismiss | 🟢 |
| `GET` | `/merchant-categories` | List mappings | 🟢 |
| `GET` | `/merchant-categories/uncategorized` | Uncategorized | 🔴 Dead |
| `GET` | `/merchant-categories/suggestions` | Suggestions | 🟢 |
| `POST` | `/merchant-categories/suggestions/{merchant}/dismiss` | Dismiss | 🟢 |
| `DELETE` | `/merchant-categories/suggestions/{merchant}/dismiss` | Undo | 🟢 |
| `POST` | `/merchant-categories` | Assign category | 🟢 |
| `DELETE` | `/merchant-categories/{merchant}` | Remove mapping | 🟢 |
| `POST` | `/normalize/apply` | Batch renormalize | 🟢 |
| `POST` | `/normalize/auto-fill` | Auto-fill merchants | 🟢 |
| `GET` | `/normalize/{job_id}` | Poll job | 🟢 |
| `GET` | `/merchant-analytics` | Merchant analytics | 🟢 |
| `GET` | `/category-rules` | List rules | 🟢 |
| `POST` | `/category-rules` | Create rule | 🟢 |
| `PUT` | `/category-rules/{id}` | Update rule | 🟢 |
| `DELETE` | `/category-rules/{id}` | Delete rule | 🟢 |
| `GET` | `/category-rules/unmapped` | Unmapped categories | 🟡 Unused |
| `GET` | `/category-rules/suggestions` | Suggestions | 🟢 |
| `POST` | `/category-rules/test` | Test conditions | 🟢 |
| `POST` | `/category-rules/apply` | Category normalize | 🟢 |
| `GET` | `/budgets` | List budgets | 🟢 |
| `POST` | `/budgets` | Create/update | 🟢 |
| `DELETE` | `/budgets/{id}` | Delete | 🟢 |
| `GET` | `/budgets/rebalance` | Suggestions | 🟢 |
| `POST` | `/budgets/rebalance/apply` | Apply | 🟢 |
| `GET` | `/dashboard/summary` | Dashboard KPIs | 🟢 |
| `GET` | `/dashboard/weekly-recap` | Weekly recap | 🟢 |
| `GET` | `/cashflow/summary` | Cash flow | 🟢 |
| `GET` | `/recurring` | Detect patterns | 🟢 |
| `POST` | `/recurring/override` | Set override | 🟢 |
| `DELETE` | `/recurring/override/{merchant}` | Remove override | 🟢 |
| `GET` | `/recurring/suggestions` | Annual fees | 🟢 |
| `POST` | `/recurring/suggestions/{id}/accept` | Accept | 🟢 |
| `POST` | `/recurring/suggestions/{id}/dismiss` | Dismiss | 🟢 |
| `GET` | `/recurring/suggestions/dismissed` | Dismissed list | 🟢 |
| `POST` | `/recurring/suggestions/dismissed/{id}/undo` | Undo | 🟢 |
| `GET` | `/recurring/deleted` | Suppressed list | 🟢 |
| `POST` | `/recurring/deleted/{merchant}/restore` | Restore | 🟢 |
| `GET` | `/reports` | List reports | 🟢 |
| `GET` | `/reports/{name}` | Download CSV | 🟢 |
| `POST` | `/reports/query` | Custom query | 🟢 |
| `GET` | `/charts/{name}` | Chart JSON | 🟢 |
| `POST` | `/reports/regenerate` | Regenerate all | 🟢 |
| `GET` | `/metric-docs/{topic}` | Metric docs | 🟢 |
| `GET` | `/version` | App version | 🟢 |
| `GET/PATCH` | `/settings` | UI settings | 🟢 |
| `GET` | `/logs` | Log lines | 🟢 |
| `GET` | `/logs/download` | Download log | 🟡 Unused |
| `GET` | `/backup/export` | Export backup | 🟢 |
| `POST` | `/backup/restore` | Restore backup | 🟢 |
| `GET` | `/backup/status` | Backup status | 🟢 |
| `GET/POST/PUT/DELETE` | `/tags` | Tag CRUD | 🟢 |
| `POST/DELETE` | `/transactions/tags` | Tag assignment | 🟢 |
| `GET` | `/transactions/{fp}/tags` | Transaction tags | 🟢 |
| `GET` | `/tags/totals` | Per-tag totals | 🟢 |
| `GET/POST/PUT/DELETE` | `/savings-goals` | Goals CRUD | 🟢 |
| `POST` | `/savings-goals/{id}/update-progress` | Update progress | 🟢 |
| `GET` | `/savings-goals/suggestions` | Suggestions | 🟢 |
| `POST` | `/monthly-summaries/generate` | Generate | 🟢 |
| `GET` | `/monthly-summaries` | List | 🟢 |
| `GET` | `/monthly-summaries/{year}/{month}` | Get | 🟢 |
| `DELETE` | `/monthly-summaries/{year}/{month}` | Delete | 🟢 |
| `POST` | `/annual-reports/generate` | Generate | 🟢 |
| `GET` | `/annual-reports` | List | 🟢 |
| `GET` | `/annual-reports/{year}` | Get | 🟢 |
| `DELETE` | `/annual-reports/{year}` | Delete | 🟢 |
| `GET/POST/PUT/DELETE` | `/net-worth/accounts` | NW accounts | 🟢 |
| `GET` | `/net-worth/summary` | NW breakdown | 🟡 Unused |
| `GET/POST/DELETE` | `/net-worth/snapshots` | NW snapshots | 🟢 |
| `GET` | `/duplicates` | Duplicate candidates | 🟢 |
| `POST` | `/duplicates/{id}/resolve` | Resolve | 🟢 |
| `GET` | `/utilities/categories` | Category taxonomy | 🟢 |
| `GET` | `/utilities/merchants` | Merchant list | 🟢 |
| `POST` | `/utilities/test-rule` | Rule tester | 🟢 |
| `GET` | `/utilities/health` | Data health | 🟢 |
| `GET` | `/accounts/` | List accounts with filters | 🟢 |
| `GET` | `/accounts/{id}` | Single account detail | 🟢 |
| `POST` | `/accounts/` | Create account | 🟢 |
| `PUT` | `/accounts/{id}` | Update account | 🟢 |
| `PATCH` | `/accounts/{id}/status` | Change status | 🟢 |
| `GET` | `/accounts/taxonomy` | CoA tree structure | 🟢 |
| `GET/POST/DELETE` | `/accounts/tags` | Payment source tags | 🟢 |
| `POST` | `/accounts/balances/update` | Bulk balance update (reconciliation) | 🟢 |
| `GET` | `/accounts/balances/history/{id}` | Balance ledger for one account | 🟢 |
| `GET` | `/accounts/balances/latest` | Latest balance for all accounts | 🟢 |
| `GET` | `/accounts/balances/stale` | Accounts not updated in > N days | 🟢 |
| `GET` | `/accounts/balances/snapshot` | Generate net worth snapshot | 🟢 |
| `GET` | `/accounts/balances/summary` | Overview KPI summary | 🟢 |
