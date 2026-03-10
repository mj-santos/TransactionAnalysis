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
- **Dark mode**: `[data-theme="dark"]` overrides on `<body>` — dark background (`#0f172a`), light text, adjusted sidebar/card/input colors; toggled via sidebar footer button, persisted in localStorage
- **Colorblind palette**: `[data-palette="colorblind"]` overrides — deuteranopia/protanopia-safe colors (`--success: #0077bb`, `--warning: #ee7733`, `--danger: #cc3311`); toggled via sidebar footer button, persisted in localStorage

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
│   ├── api.py                  ← FastAPI app factory (create_app); ALL endpoints defined here (~5899 lines)
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
│   │   ├── query_helpers.py    ← INCOME_FILTER constant — canonical income SQL condition
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
│       ├── index.html          ← Single-page UI (1,912 lines); all pages embedded as hidden sections
│       └── static/
│           ├── app.js          ← All UI logic (~6,998 lines); no bundler/framework
│           ├── style.css       ← All styles (~1,635 lines)
│           └── table_controls.js ← Two reusable widgets (~370 lines):
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
    ├── test_merchant_groups.py  ← grouped boolean logic tests for merchant rules engine
    ├── test_models.py
    ├── test_money.py
    ├── test_pipeline_api.py
    ├── test_income_classification.py ← income rule regression tests (BUG-6/7/8)
    ├── test_recurring.py       ← recurring detection engine tests
    ├── test_utilities.py       ← Utilities endpoint tests
    ├── test_dashboard.py          ← version endpoint tests (dynamic version from pyproject.toml)
    ├── test_merchant_category_edit.py ← inline category edit, override, fix-for-all, merchant bulk tests
    ├── test_merchant_list_edit.py ← merchant-level category edit, one-row-per-merchant, override respect, orphan detection tests
    ├── test_bulk_actions.py    ← bulk-assign-merchant, merchant search, changes() audit tests
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
| Utilities | `#page-utilities` | `loadUtilCategories()` + `loadUtilMerchants()` + `loadUtilDuplicates()` + `loadUtilHealth()` | ✅ Working |
| Settings | `#page-settings` | `loadSettings()` | ✅ Working (BUG-3 fixed) |

### Global Features (visible on all pages)

- **Global Transaction Search**: persistent search bar in topbar; queries `GET /transactions/search?q=<query>&limit=50`; searches description, merchant, amount (supports `>50`, `<200`, `50-100` operators), category_normalized; floating results panel with date, merchant, amount, category, CC/Bank badge; keyboard navigation (↑↓ Enter Esc); `/` shortcut focuses search; click result navigates to correct tab with date pre-filtered and transaction highlighted (3s highlight fade); 300ms debounce, minimum 2 characters; click-outside-to-close

### Feature Details

**Dashboard (`#page-dashboard`)**
- MTD spend KPI card, transaction count card, unreviewed count KPI card
- Month navigation (prev/next arrows) — `dashboardPrevMonth()`, `dashboardNextMonth()`
- Top categories bar chart (horizontal, CSS-rendered) — **clickable rows open category drill-down modal** showing all transactions for that category + month with subtotal; "View All in Transactions" navigates to Bank tab pre-filtered
- Budget tracker with inline add/edit/delete form — `openBudgetForm()`, `saveBudget()`, `deleteBudget()`
- Budget rebalance suggestions — `loadRebalanceSuggestions()`, `applyRebalance()`: analyses avg monthly spend vs budget, suggests adjustments for categories >=15% over/under, user selects and confirms before applying
- **Spending Alerts & Thresholds**: in-app alert banners for categories at ≥80% (yellow warning) and ≥100% (red exceeded) of monthly budget; budget status overview card with green/yellow/red status chips per category; color-coded status dots on budget tracker bars; dismissible banners; alerts auto-reset each month
- **Savings Goals** widget: progress bars for each goal, inline create/edit/delete, manual progress updates (set or add mode), auto-calculated monthly savings needed to hit target by deadline, suggested monthly amount from avg net cash flow
- **Monthly Summary** button: opens modal with plain-language narrative, KPI grid (spent/income/net/txns), **clickable top categories** with delta bars (opens drill-down for that month), top merchants chips, biggest purchase card; month navigation ←/→; save/regenerate summaries; "Browse History" opens stored summaries list
- **Net Worth** widget: assets/liabilities/net KPI row with trend vs last snapshot; account list with type badges and inline edit/delete; add account form (name, type dropdown, balance); save snapshot button captures point-in-time balances; collapsible history panel with mini bar chart and snapshot list
- **Year in Review** button: opens modal with annual report — total income/spent/net saved KPIs, biggest/lightest months, recurring costs estimate, month-by-month bar chart, top 5 categories with progress bars, top 5 merchants ranked list; year navigation ←/→; save/regenerate reports; print/PDF export via browser print dialog; "Browse Past Reports" opens stored reports history with view/delete per year
- Recent transactions table (last 10) with unreviewed dot indicators
- Unreviewed count badge on sidebar Dashboard nav link
- API: `GET /dashboard/summary?year=&month=`, `GET /budgets/rebalance`, `POST /budgets/rebalance/apply`, `GET/POST/PUT/DELETE /savings-goals`, `POST /savings-goals/{id}/update-progress`, `GET /savings-goals/suggestions`, `POST /monthly-summaries/generate?year=&month=`, `GET /monthly-summaries`, `GET /monthly-summaries/{year}/{month}`, `DELETE /monthly-summaries/{year}/{month}`, `GET/POST/PUT/DELETE /net-worth/accounts`, `GET /net-worth/summary`, `GET/POST/DELETE /net-worth/snapshots`, `POST /annual-reports/generate?year=`, `GET /annual-reports`, `GET /annual-reports/{year}`, `DELETE /annual-reports/{year}`

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
- Filter bar: date range, description search, merchant filter, category filter, account filter, **year selector** (scopes presets to selected year; defaults to current year or most recent with data)
- Quick date preset buttons: This Month, Last Month, 3 Months, YTD, All (scoped to selected year)
- Import Source dropdown (per statement type)
- Group-by selector (including `category_normalized`, `category_parent`)
- "Show Unreviewed Only" toggle filter
- Sortable columns
- Infinite scroll / "Load more" (100 rows per page)
- Totals footer row
- Per-transaction "Mark as Reviewed" button with unreviewed dot indicator
- "Mark All Reviewed" bulk action (respects current filters)
- Tag filter dropdown — filters transactions by assigned tag
- Per-row tag chips showing assigned tags, "+tag" button opens tag assignment popup
- Tag assignment popup: checkboxes for all tags, toggle to assign/remove per transaction
- **Bulk Actions**: select-all checkbox in header + per-row checkboxes; bulk action bar (blue) appears when ≥1 selected with buttons: Assign Category, Mark Reviewed, Exclude, Assign Merchant (inline type-ahead panel), Assign Tag, Clear Selection ×; selected rows get left border accent + light blue tint; "{N} selected" counter updates in real time
- **Inline Category Editing**: click category cell to edit via `openCategoryPicker`; sets `category_override=TRUE` on save to protect from batch normalization; override badge ("edited" pill) shown on overridden rows with click-to-reset; "Fix for All?" prompt after save offers to apply category to all transactions from same merchant (auto-dismiss 8s); `_fixForAllMerchant()` updates merchant→category map and patches non-override transactions
- **Transaction Notes**: per-transaction notes via pencil icon; inline popup editor with textarea; auto-save on Enter or Save click; PATCH endpoint updates `notes` field
- **Split Transactions**: split one transaction into N sub-rows across categories; parent marked `is_split=TRUE` and excluded from totals; children carry `split_parent_fingerprint`; "split" badge on child descriptions; unsplit restores parent and removes children. **⚠️ AUDIT-1: Backend endpoints exist but `openSplitModal()` and `unsplitTransaction()` are never called from any UI element — the split feature has no entry point.**
- API: `GET /transactions`, `GET /transactions/totals`, `GET /transactions/sources`, `GET /transactions/years`, `POST /transactions/mark-reviewed`, `POST /transactions/mark-all-reviewed`, `PATCH /transactions/{fingerprint}`, `POST /transactions/{fingerprint}/split`, `DELETE /transactions/{fingerprint}/split`

**Cash Flow (`#page-cashflow`)**
- Summary KPI cards: Income (green), Spending (red), Net (color-coded), Month-over-Month delta
- Time period filter dropdown: This Month, Last Month, Last 3 Months, Last 12 Months, per-year options (from transaction data), Custom Range
- Custom date range inputs (shown when "Custom Range" selected)
- Toggleable "Include transfers" checkbox (excludes payment subtypes and transfer categories by default)
- Monthly bar chart: paired income/spending bars per month, CSS-rendered (no Chart.js dependency)
- Spending by category breakdown: horizontal bars with percentage labels (top 12) — **clickable rows open category drill-down modal** with date range from current period
- Monthly detail table: Income, Spending, Net per month with color-coded values
- Month-over-month delta indicator showing spending change vs prior month
- API: `GET /cashflow/summary?period=&start_date=&end_date=&include_transfers=`

**Reports (`#page-reports`)**
- Static report cards: spend_by_month_category, cashflow_by_month, spend_by_merchant, totals_by_account, top_merchants
- Per-report: view as chart (bar, time-series), download CSV
- Chart viewer with group-by and date-from/date-to filters — **rows with a category column are clickable** for drill-down (date range inferred from row's date/month column if present)
- Custom Report Builder: add/remove filters, group-by, bucket (day/week/month/year), order-by, limit
- Quick date presets in custom report
- Results rendered as table with download-to-CSV button
- API: `GET /reports`, `GET /reports/{name}`, `GET /charts/{name}`, `POST /reports/query`, `POST /reports/regenerate`, `GET /metric-docs/{topic}`

**Merchants (`#page-merchant-rules`)**
- **Merchant Intelligence** panel: `loadMerchantAnalytics()` → `GET /merchant-analytics`
  - Per-merchant: total spend all-time, monthly average, transaction frequency, months active, last transaction date
  - 3-month trend indicator (increasing/decreasing/flat) with MoM percentage
  - Accelerating spend flag (red badge) for >20% MoM increase
  - Mini sparkline bars showing last 3 months of spend per merchant
  - Sort by: total spend, frequency, recent activity, trend
  - Search/filter by merchant name (debounced)
  - KPI row: total merchants, accelerating count, shown count
- Recommended Normalization Rules panel: `loadRuleSuggestions()` → `GET /merchant-rules/suggestions`
  - Analyzes raw descriptions; suggests pattern → merchant rules
  - Accept, Edit, Dismiss per suggestion; Accept All
- Merchant Normalization Rules CRUD table: `loadMerchantRules()` → `GET /merchant-rules`
  - **Inline search bar**: real-time filter across pattern, merchant, match_type columns; "X of N rules" count; Escape to clear
  - Add/Edit rules with compound AND/OR conditions, match types (contains/startswith/regex), priority, negation
  - Test rule against live data; paginated match results
  - Delete with confirmation
- Re-normalize All Transactions button: `startRenormalize()` → `POST /normalize/apply` (background job, polled)
- Uncategorized Merchants panel: `loadUncategorized()` → `GET /merchant-categories/uncategorized`
  - Inline category assignment dropdown + assign button per merchant
  - Backfills category onto all transactions for that merchant
  - **"Show categorized merchants too" toggle**: fetches `GET /merchant-categories` and displays categorized merchants below the uncategorized list with inline category edit via `openCategoryPicker`
- **Collapsible panels**: Recommended Rules, Merchant Rules, Uncategorized panels all collapse/expand with item count badges; scroll-capped containers; collapse state persisted in localStorage
- API: Full CRUD on `/merchant-rules`, `/merchant-categories`, `/normalize/apply`, `/normalize/{job_id}`, `GET /merchant-analytics`

**Categories (`#page-category-rules`)**
- Suggested Category Mappings panel: `loadCatSuggestions()` → `GET /category-rules/suggestions`
  - Scans raw bank category strings; matches against built-in taxonomy
  - Accept (creates rule), Edit (opens form), Dismiss per suggestion; Accept All
- Suggested Merchant Categories panel: `loadCategorySuggestions()` → `GET /merchant-categories/suggestions`
  - Keyword-heuristic matching of merchant names to categories
  - Accept assigns category to merchant via `/merchant-categories`
- Category Normalization Rules CRUD table: `loadCategoryRules()` → `GET /category-rules`
  - **Inline search bar**: real-time filter across raw_category, normalized category, parent group columns; "X of N rules" count; Escape to clear
  - Maps raw bank category → normalized category + parent group
  - **Grouped condition builder**: same pattern as merchant rules — 1+ groups with AND/OR combiner, conditions with exact/contains/starts_with match types, NOT support; legacy exact-match rules auto-load as single condition on edit
  - Inline editor form with parent group dropdown (fixed list of 12 parents)
- **Collapsible panels**: Suggested Mappings, Suggested Merchant Categories, Category Rules panels all collapse/expand with item count badges; scroll-capped containers; collapse state persisted in localStorage
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

**Utilities (`#page-utilities`)**
- Sidebar nav item with pending-duplicates badge (between Categories and Settings)
- 5 collapsible card sections following standard collapsible panel pattern:
  - **Category List**: Full searchable taxonomy from `BUILT_IN_CATEGORY_MAP` + user categories; grouped by parent with subcategories; transaction counts per category; real-time JS filter
  - **Merchant List**: One row per normalized merchant with transaction count, total spend, assigned category (from `merchant_category_map` JOIN), last seen date; sortable (count/name/last seen); inline merchant-level category edit via `openCategoryPicker` — writes `merchant_category_map` and re-normalizes all transactions for that merchant (respects `category_override`); search filter; bulk select checkboxes with bulk action bar (Assign Category, Remove Category, Clear Selection) — operations run sequentially per merchant (DuckDB single-writer)
  - **Rule Tester**: Paste transaction description → shows full classification trace: raw → merchant rule match → normalized merchant → category → parent
  - **Duplicate Review**: Lists pending `duplicate_candidates` with side-by-side transaction details; action buttons: Keep Both / Remove Newer / Not a Duplicate; empty state message when clean
  - **Data Health**: Read-only dashboard with 6 metrics (uncategorized txns, unreviewed txns, merchants without category, no merchant match, pending duplicates, orphaned categories); each metric links to relevant page; orphaned categories metric shows "Fix Now" button that runs full `POST /normalize/apply`
- **Near-Duplicate Detection**: Runs automatically after every import commit as part of `_commit_bg`; flags transactions with same merchant, amount within 1%, date within 3 days; results stored in `duplicate_candidates` table; non-blocking banner shown on import page linking to Duplicate Review
- **Structured Category Picker**: Uncategorized Merchants input replaced with type-ahead dropdown populated from category taxonomy; "Parent > Subcategory" format; [ Custom ] option for free-text entry
- API: `GET /duplicates`, `POST /duplicates/{id}/resolve`, `GET /utilities/categories`, `GET /utilities/merchants`, `POST /utilities/test-rule`, `GET /utilities/health`

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
- **Tag Management** card:
  - Create/edit/delete custom tags with name and color picker
  - Tag list with colored badges, edit/delete buttons
  - Per-tag totals panel: transaction count and total spend per tag (all-time)
  - Tags loaded on Settings page visit via `loadTags()` → `GET /tags`
- API: `GET /backup/export`, `POST /backup/restore`, `GET /backup/status`, `GET/POST/PUT/DELETE /tags`, `POST/DELETE /transactions/tags`, `GET /transactions/{fingerprint}/tags`, `GET /tags/totals`

**Power User Features (UI-only, no new API endpoints)**
- **Keyboard Shortcuts**: global `keydown` listener — `j`/`k` navigate transaction rows, `r` mark reviewed, `c` inline category edit, `x` toggle select, `/` focus global search bar, `?` show help modal, `1`-`9` switch tabs, `Esc` close modals/search panel; highlighted row indicator; keyboard help modal accessible from sidebar footer link
- **Dark/Light Mode Toggle**: sidebar footer button toggles `[data-theme="dark"]` on `<body>`; preference saved in localStorage; `toggleTheme()` / `_updateThemeUI()`
- **Colorblind Palette Toggle**: sidebar footer button toggles `[data-palette="colorblind"]` on `<body>`; deuteranopia/protanopia-safe colors; preference saved in localStorage; `toggleColorblind()`
- **Onboarding Flow**: 3-step guided modal for first-time users (import → categories → budgets); shown automatically on first visit; dismissible; "Don't show again" saved in localStorage; `_checkOnboarding()` / `onboardingGo()` / `closeOnboarding()`

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
| `notes` | TEXT | User-editable note per transaction (added by migration) |
| `is_split` | BOOLEAN DEFAULT FALSE | TRUE = parent row that has been split; excluded from totals (added by migration) |
| `split_parent_fingerprint` | TEXT | FK to parent's `transaction_fingerprint`; set on child split rows (added by migration) |
| `category_override` | BOOLEAN DEFAULT FALSE | When TRUE, category normalization jobs skip this row — preserves user's manual category edit (added by migration) |

**Index:** `UNIQUE INDEX idx_tx_fingerprint ON transactions_norm(transaction_fingerprint)`

**Key relationships:**
- `file_hash` → `raw_files.file_hash`
- `run_id` → `runs.run_id`
- `merchant` → `merchant_category_map.merchant` (soft, not enforced)
- `category` → `category_rules.raw_category` (soft, not enforced)

**⚠️ Schema notes:**
- 11 columns exist only via migration, not in base DDL: `statement_type`, `run_id`, `transaction_subtype`, `resolved_amount`, `category_normalized`, `category_parent`, `unreviewed`, `notes`, `is_split`, `split_parent_fingerprint`, `category_override`
- No explicit UNIQUE constraint on `transaction_fingerprint` in DDL — dedup relies on the separate CREATE UNIQUE INDEX statement

---

### `duplicate_candidates` — near-duplicate detection results

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-increment via `seq_duplicate_candidates_id` |
| `fingerprint_a` | TEXT NOT NULL | Existing transaction fingerprint |
| `fingerprint_b` | TEXT NOT NULL | Newly imported transaction fingerprint |
| `similarity_score` | DECIMAL(3,2) | 0.0–1.0 similarity score |
| `reason` | TEXT | Human-readable explanation (e.g. "same merchant, amount within 1%, date within 2 days") |
| `status` | TEXT DEFAULT 'pending' | `'pending'`, `'confirmed_duplicate'`, `'not_duplicate'` |
| `detected_at` | TEXT | ISO timestamp of detection |
| `resolved_at` | TEXT | ISO timestamp of resolution (nullable) |

**Key relationships:**
- `fingerprint_a` → `transactions_norm.transaction_fingerprint`
- `fingerprint_b` → `transactions_norm.transaction_fingerprint`

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
| `conditions` | TEXT | JSON: grouped `{"groups": [{"group_logic": "OR"\|"AND", "conditions": [{pattern, match_type, negate}]}]}` or legacy flat array. All groups must pass (implicit AND between groups). |
| `logic` | TEXT DEFAULT 'AND' | `'AND'` or `'OR'` — used as group_logic when legacy flat conditions are auto-migrated to grouped format on read |

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
| `raw_category` | TEXT NOT NULL UNIQUE | Raw bank category string (legacy exact-match) or label for grouped rules |
| `category` | TEXT NOT NULL | Normalized subcategory (e.g. "Restaurants") |
| `parent` | TEXT NOT NULL | Parent group (e.g. "Food & Dining") |
| `conditions` | TEXT | JSON grouped conditions or NULL for legacy exact-match. Format: `{"groups": [{"group_logic": "AND"|"OR", "conditions": [{"pattern": str, "match_type": "exact"|"contains"|"starts_with", "negate": bool}]}]}` |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

Lookup priority: grouped condition rules (DB, `conditions` IS NOT NULL) > exact-match user rules (DB, `conditions` IS NULL) > built-in `BUILT_IN_CATEGORY_MAP` in `category_rules.py` > fallback (keep raw, assign parent "Other"). Backward-compatible: single group + single condition + match_type="exact" + no negate → stored as legacy (conditions=NULL).

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

### `tags` — user-defined transaction tags

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `name` | TEXT NOT NULL UNIQUE | Tag display name |
| `color` | TEXT DEFAULT '#3b82f6' | Hex color code |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

---

### `transaction_tags` — many-to-many tag assignments

| Column | Type | Notes |
|---|---|---|
| `transaction_fingerprint` | TEXT NOT NULL | FK to `transactions_norm.transaction_fingerprint` |
| `tag_id` | BIGINT NOT NULL | FK to `tags.id` |
| `created_at` | TEXT NOT NULL | ISO timestamp |

**Unique constraint:** `(transaction_fingerprint, tag_id)`

---

### `savings_goals` — user savings targets with progress tracking

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `name` | TEXT NOT NULL | Goal display name (e.g. "Emergency Fund") |
| `target_amount` | DECIMAL(18,2) NOT NULL | Target savings amount |
| `current_amount` | DECIMAL(18,2) DEFAULT 0 | Current amount saved (manual updates) |
| `target_date` | TEXT | Optional ISO date deadline |
| `linked_account` | TEXT | Optional account name for reference |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

---

### `monthly_summaries` — stored monthly summary reports

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `year` | INTEGER NOT NULL | Summary year |
| `month` | INTEGER NOT NULL | Summary month (1-12) |
| `summary_json` | TEXT NOT NULL | JSON blob with all metrics (spent, income, net, categories, merchants, biggest txn) |
| `narrative` | TEXT NOT NULL | Plain-language summary paragraph |
| `created_at` | TEXT | ISO timestamp |

UNIQUE constraint on `(year, month)`.

---

### `nw_accounts` — net worth account balances

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `name` | TEXT NOT NULL | Account display name (e.g. "Chase Checking") |
| `acct_type` | TEXT NOT NULL | One of: `checking`, `savings`, `investment`, `credit_card`, `loan`, `other` |
| `balance` | DECIMAL(18,2) DEFAULT 0 | Current balance (positive for assets, positive for liabilities too — `is_asset` flag determines sign) |
| `is_asset` | BOOLEAN DEFAULT TRUE | TRUE for checking/savings/investment/other; FALSE for credit_card/loan |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

---

### `nw_snapshots` — point-in-time net worth snapshots

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `snapshot_date` | TEXT NOT NULL | ISO date when snapshot was taken |
| `total_assets` | DECIMAL(18,2) DEFAULT 0 | Sum of all asset account balances |
| `total_liab` | DECIMAL(18,2) DEFAULT 0 | Sum of all liability account balances |
| `net_worth` | DECIMAL(18,2) DEFAULT 0 | total_assets - total_liab |
| `detail_json` | TEXT NOT NULL | JSON array of account details at snapshot time |
| `created_at` | TEXT | ISO timestamp |

---

### `annual_reports` — stored annual year-in-review reports

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-seq |
| `year` | INTEGER NOT NULL UNIQUE | Report year |
| `report_json` | TEXT NOT NULL | JSON blob with all metrics (income, spent, net, categories, merchants, monthly, biggest/lightest month, recurring) |
| `narrative` | TEXT NOT NULL | Plain-language summary paragraph |
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

**BUG-16: `batch_renormalize()` ignores `category_override` — clobbers user manual edits**
- File: `merchant_rules.py`, Line: 345
- Description: `batch_renormalize()` fetches ALL rows from `transactions_norm` with no `WHERE COALESCE(category_override, FALSE) = FALSE` filter. Every other normalization path (`apply_category_rules`, `renormalize_merchant`) correctly skips override rows. Clicking "Re-normalize All Transactions" on the Merchants page will silently destroy all manual category edits.
- Impact: **HIGH** — data loss of user manual category overrides
- Fix: Add `WHERE COALESCE(category_override, FALSE) = FALSE` to the SELECT at line 345.

**BUG-17: `PATCH /transactions/{fp}` accepts `excluded` field but column doesn't exist**
- File: `api.py`, Line: 1916
- Description: The allowed fields set includes `"excluded"` but no `excluded` column exists in `transactions_norm` DDL or any migration. Any PATCH request with `{"excluded": true}` will produce a DuckDB SQL error.
- Impact: Medium — bulk "Exclude" action from the UI will fail at runtime.
- Fix: Either add `excluded` column via migration, or remove it from allowed fields.

**BUG-18: Two category picker implementations — `_buildCategoryPickerHTML()` not consolidated**
- File: `app.js`, Lines: 6930-6995
- Description: Despite PROJECT.md documenting `openCategoryPicker()` as the ONLY category picker, a second complete implementation `_buildCategoryPickerHTML()` exists with 6 supporting functions (`_openCatPicker`, `_filterCatPicker`, `_renderCatPickerOptions`, `_selectCatOption`, `_selectCatCustom`). Used by: uncategorized merchants panel (line 3491) and merchant category suggestions (line 3729). The two implementations have different behavior: A supports "Remove Category", B supports "[ Custom ]" free-text entry.
- Impact: Low — both work, but maintenance risk of diverging behavior.
- Fix: Consolidate into `openCategoryPicker()` with `allowCustom` option.

**BUG-19: `bulkAssignCategory()` uses `prompt()` instead of category picker**
- File: `app.js`, Line: 6196
- Description: The bulk "Assign Category" action on CC/Bank transaction pages uses `prompt()` (browser built-in dialog) for category input instead of `openCategoryPicker()`. Similarly, bulk tag assignment (line 6234) uses `prompt()`. These bypass the structured category taxonomy entirely.
- Impact: Medium — users can type arbitrary categories that don't match the taxonomy.
- Fix: Replace `prompt()` with `openCategoryPicker()` for category, and a tag selector for tags.

**BUG-20: Dark mode selectors for run-status badges will never match**
- File: `style.css`, Lines: 1377-1379
- Description: Dark theme uses `.run-status-success` (hyphenated single class) but light theme and JS use `.run-status.success` (compound classes). The dark selectors `.run-status-success`, `.run-status-error`, `.run-status-running` will never match any element.
- Impact: Low — run status badges have no dark mode styling.
- Fix: Change to `[data-theme="dark"] .run-status.success` etc.

**BUG-14: Data Health "Uncategorized transactions" link hardcodes bank-transactions tab**
- File: `app.js`, Line: ~6825
- Description: Data Health metric "Uncategorized transactions" navigates to `bank-transactions` but uncategorized transactions can exist in both CC and bank tabs. The health API (`GET /utilities/health`) returns only a count, not per-statement_type breakdown, so `resolveTransactionTab()` cannot be applied without fetching transaction data first.
- Impact: Low — user may not see uncategorized CC transactions when clicking the link.
- Fix: Either split the health metric into CC/bank counts, or fetch a sample of uncategorized transactions to resolve the tab.

**BUG-15: Data Health "Unreviewed transactions" link hardcodes bank-transactions tab**
- File: `app.js`, Line: ~6829
- Description: Same issue as BUG-14 but for unreviewed transactions. Navigates to `bank-transactions` but unreviewed transactions span both tabs.
- Impact: Low — user may not see unreviewed CC transactions when clicking the link.
- Fix: Same approach as BUG-14.

### Previously Fixed Bugs

**BUG-6/7/8 (FIXED): Income classification — CC payments/refunds counted as income**
- All income queries across the app (Monthly Summary, Annual Report, Cash Flow, transaction totals, tag totals, analytics CSV reports) now use `amount > 0 AND statement_type = 'bank'`. CC positive amounts (payments, refunds, adjustments) are never counted as income. See `tests/test_income_classification.py` for regression tests. Fixed in v2.13.1.

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

**BUG (FIXED): Restore connection conflict after Sprint C (DuckDB single-writer violation)**
- All 9 Sprint C functions (`_detect_duplicates`, `_create_export_payload`, `resolve_duplicate`, `list_duplicates`, `utilities_categories`, `utilities_merchants`, `utilities_test_rule` ×2, `utilities_health`) now use `conn = None; try: ... finally: conn.close()` pattern. Restore endpoint (`POST /backup/restore`) also wrapped with try/finally. Added restore lock: returns HTTP 409 if background jobs are active or another restore is in progress (`_restore_in_progress` flag). Fixed in v2.17.1.

**BUG-9 (FIXED): Bulk Assign Category sent fingerprints as merchant names**
- `bulkAssignCategory()` in app.js iterated fingerprints and called `POST /merchant-categories` with `{merchant: fingerprint, category: cat}` — this created merchant_category_map entries keyed by fingerprint strings instead of actual merchant names, and did not update the selected transactions' categories. Fixed in v2.22.0 to use `PATCH /transactions/{fp}` with `category_normalized` field.

**BUG-10 (FIXED): Bulk action bar buttons invisible**
- Buttons in the `.bulk-bar` (blue background) used `btn-secondary` class which sets `background: var(--card-bg)` (white) and `color: var(--text)` (dark) — making white buttons with dark text that appeared invisible against the blue bar. The `.bulk-bar button` rule had lower specificity than `.btn-secondary`. Fixed in v2.22.0 by using `.bulk-bar .btn` with `background: rgba(255,255,255,.15); color: #fff; border: 1px solid rgba(255,255,255,.4)`.

**BUG (FIXED): Utilities category list column name mismatch**
- `GET /utilities/categories` queried `category_rules` using `normalized_category` and `parent_category` — columns that don't exist. The actual schema uses `category` and `parent`. Utilities endpoints were written against incorrect assumed column names rather than the actual `category_rules` table schema. Fixed in v2.17.2.

**BUG-11 (FIXED): `SELECT changes()` SQLite function used in DuckDB**
- Files: `api.py` (4 occurrences), `load.py` (1 occurrence)
- Description: `changes()` is a SQLite-only function that returns the number of rows affected by the last INSERT/UPDATE/DELETE. DuckDB does not support it, causing bulk operations (mark-reviewed, mark-all-reviewed, unsplit, patch transaction) to fail silently or raise errors.
- Fix: Replaced all 5 occurrences with DuckDB-compatible patterns: COUNT queries before mutations, existence checks, and row count tracking. In `load.py`, replaced INSERT OR IGNORE + `changes()` with pre-insert existence check pattern. Fixed in v2.23.1.

**BUG-13 (FIXED): Sidebar version display is static — shows 2.0.0 instead of current version**
- File: `pyproject.toml`
- Description: `pyproject.toml` `[project] version` was never incremented past `2.0.0` despite 24 feature releases. The sidebar version display correctly fetches `GET /version` which reads from `importlib.metadata.version("finance_etl")`, but that reflects the installed package metadata — which comes from `pyproject.toml`. The display chain worked; the source data was stale.
- Fix: Updated `pyproject.toml` version to `2.24.1`. Added version sync rule to Section 7 requiring pyproject.toml to be incremented on every commit. Fixed in v2.24.1.

**BUG-12 (FIXED): Backup/restore uses `SELECT *` — misses migration-added columns**
- File: `api.py` (backup export + restore)
- Description: Backup export used `SELECT * FROM transactions_norm` which relies on column order matching the restore INSERT. Migration-added columns (11 total) may not appear in a consistent order with `SELECT *`, and future migrations could silently break backup roundtrips.
- Fix: Added `_TABLE_COLUMNS` dict with explicit column list for `transactions_norm` (26 columns). Export uses explicit SELECT, restore INSERT matches exactly. Other tables without migration columns continue using `SELECT *`. Fixed in v2.23.2.

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
- `app.js:3093` — `addConditionRow()`: superseded by `addConditionGroup()`; only self-references internally
- `app.js:4569` — `deleteBudget()`: fully implemented but no UI element calls it (no delete button rendered)
- `app.js:2734` — `openSplitModal()`: function exists but no UI element triggers it (split feature is dead UI)
- `app.js:2832` — `unsplitTransaction()`: companion to `openSplitModal()`, also never called
- `app.js:6930-6995` — `_buildCategoryPickerHTML()` + 5 helpers: second category picker implementation, should be consolidated into `openCategoryPicker()`
- `api.py:1173` — `POST /wizard/validate`: never called from frontend (validates locally instead)
- `api.py:1304` — `GET /wizard/profiles`: never called from frontend
- `api.py:5320` — `DELETE /recurring/override/{merchant}`: only mentioned in a JS comment, never invoked
- `api.py:2035` — `DELETE /transactions/{fingerprint}/split`: only reachable through dead `unsplitTransaction()`
- `hashing.py:18` — `sha256_str()`: defined but never imported/called
- `wizard_mapping.py:296` — `get_canonical_fields_for_type()`: defined but never called
- **Tracked `.DS_Store` and `.env` files**: 5 `.DS_Store` files and `.env` are tracked in git despite being listed in `.gitignore` (added before gitignore existed). Should be untracked via `git rm --cached`.

### Audit 1 — Codebase vs PROJECT.md Reality Check (2026-03-10)

#### FEATURE INVENTORY STATUS

**✅ Complete (18 of 20 checked features):**
openCategoryPicker shared component, merchant_filter on POST /normalize/apply, duplicate detection + utilities tab (5 sections), weekly recap banner, unreviewed nudge widget, budget pace indicator, year filter on transactions, global search, backup/restore full column coverage, resolveTransactionTab, transaction notes, savings goals, monthly summaries, net worth, annual reports, tags, recurring transactions, split transactions (backend only)

**⚠️ Partial (1):**
- Grouped mode category edit: `openCategoryPicker` is never invoked in grouped mode — the `&& fp` guard at `app.js:2569` silently disables editing when rows lack a fingerprint (all grouped/aggregated rows)

**❌ Broken (1):**
- `batch_renormalize()` ignores `category_override` (BUG-16) — "Re-normalize All" clobbers manual edits

#### DUPLICATE LOGIC FOUND

| Component | Count | Locations | Recommendation |
|---|---|---|---|
| Category picker implementations | **2** | `openCategoryPicker()` (line 6340) + `_buildCategoryPickerHTML()` (line 6930) | Consolidate to single `openCategoryPicker()` with `allowCustom` option |
| `prompt()` for category/tag input | **2** | `bulkAssignCategory` (line 6196), bulk tag assign (line 6234) | Replace with `openCategoryPicker()` / tag selector |
| Income filter inline copies | **2** | `api.py:3779`, `api.py:3795` (tag totals with `tn.` alias) | Add comment referencing INCOME_FILTER; can't use constant due to table alias |
| Income filter stale tooltip | **1** | `api.py:2606` — tooltip omits `statement_type = 'bank'` condition | Update tooltip text |
| POST /merchant-categories callers | **7** | Lines 3506, 3527, 3752, 3778, 6513, 6678, 6732 | Inconsistent: only lines 6678 and 6732 pass `source` field |
| Hardcoded tab navigation (bypassing resolveTransactionTab) | **2** | `app.js:6869` (uncategorized health), `app.js:6873` (unreviewed health) | Already filed as BUG-14/BUG-15 |
| POST /normalize/apply triggers | **2** | `startRenormalize` (line 3407, polls), `_fixOrphanedCategories` (line 6903, no poll) | Make orphan fix also poll for completion |

#### DEAD CODE

**Dead JS functions:** `addConditionRow` (3093), `deleteBudget` (4569), `openSplitModal` (2734), `unsplitTransaction` (2832)

**Dead API endpoints:** `GET /mappings` (786), `POST /runs` (897), `POST /wizard/validate` (1173), `GET /wizard/profiles` (1304), `DELETE /recurring/override/{merchant}` (5320), `DELETE /transactions/{fp}/split` (2035)

**Dead Python functions:** `sha256_str()` (hashing.py:18), `get_canonical_fields_for_type()` (wizard_mapping.py:296)

**Dead CSS classes:** `.completed` (1471), `.divider` (357), `.form-row` (174), `.inline-cat-input` (1390), `.onboarding-overlay` (1392), `.section-actions` (358), `.spinner` (236)

**Broken dark mode selectors:** `.run-status-success` / `.run-status-error` / `.run-status-running` (lines 1377-1379) should be `.run-status.success` etc.

#### SCHEMA GAPS

| Table.Column | Issue |
|---|---|
| `transactions_norm.excluded` | Referenced in PATCH endpoint allowed fields but column does not exist in DDL or migrations |
| `raw_files` | Excluded from `_BACKUP_TABLES` — lost on restore; `file_hash` references become dangling |
| `raw_files.original_path/file_size_bytes/header_json/profile_path/ingested_at` | Write-only: populated during ingest but never queried |
| `runs.notes` | Present in DDL but never written to by any code path |
| `schema_version.version` | Seeded with `1` but never incremented by any migration |
| Split child INSERT | Omits `category_override`; children default to FALSE (implicit design choice) |

#### API CONTRACT MISMATCHES

**Undocumented endpoints (missing from API reference table):**
- `POST /transactions/{fingerprint}/split`
- `DELETE /transactions/{fingerprint}/split`

**Path parameter name mismatches (doc says `{id}`, code uses specific names):**
- `/merchant-rules/{id}` → actual `{rule_id}` (PUT, DELETE)
- `/category-rules/{id}` → actual `{rule_id}` (PUT, DELETE)
- `/budgets/{id}` → actual `{budget_id}` (DELETE)
- `/savings-goals/{id}` → actual `{goal_id}` (PUT, DELETE, update-progress)
- `/net-worth/accounts/{id}` → actual `{account_id}` (PUT, DELETE)
- `/net-worth/snapshots/{id}` → actual `{snapshot_id}` (DELETE)
- `/duplicates/{id}/resolve` → actual `{dup_id}` (POST)

**Frontend status inaccuracies (PROJECT.md says "Called" but never called):**
- `POST /wizard/validate` — frontend validates locally
- `GET /wizard/profiles` — never referenced
- `GET /logs/download` — no fetch call found
- `DELETE /recurring/override/{merchant}` — only in a JS comment
- `GET /net-worth/summary` — no fetch call found

#### CRITICAL FINDINGS (ranked by risk)

1. **BUG-16: `batch_renormalize()` ignores `category_override`** — "Re-normalize All Transactions" silently destroys all manual category edits. Data loss risk.
2. **BUG-17: `excluded` column doesn't exist** — PATCH endpoint will throw DuckDB error when bulk "Exclude" is used.
3. **Split transaction UI is dead** — `openSplitModal()` and `unsplitTransaction()` are never called from any UI element. The split feature appears to have lost its entry point.
4. **Two category picker implementations** diverging in behavior — maintenance risk, users get inconsistent UX between uncategorized panel and other edit surfaces.
5. **`raw_files` excluded from backup** — restore loses file registry, breaking file_hash references.

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
- **DuckDB single-writer constraint**: DuckDB allows only one active read-write connection at a time per database file. All `get_connection()` calls MUST use `conn = None; try: conn = get_connection(...); ... finally: if conn: conn.close()` to guarantee release. Read-only connections (`read_only=True`) can coexist but must also be released promptly. Background tasks (`_commit_bg`, `_detect_duplicates`) must close connections before returning. The restore endpoint checks for active background jobs and returns HTTP 409 if any are running (`_restore_in_progress` flag + `_async_runs` status check).
- **`_staged_runs` is persisted**: Staged run state is stored in `pipeline._staged_runs: dict[str, dict]` in memory and persisted to `data/staged/` as JSON sidecar files (BUG-2 fix).
- **YAML wizard profiles** persist column mappings per institution/account. On re-upload, the wizard auto-matches headers.
- **`source='user'` vs `source='learned'`** in `merchant_category_map`: User-assigned categories are never overwritten by the learn mechanism.
- **Merchant rule grouped boolean logic**: Rules have 1+ condition groups. Each group has its own AND/OR combiner applied within the group. Inter-group logic is always AND (implicit — not stored, not configurable). Legacy flat conditions (list) are auto-migrated to a single group on read. This maps to user intent: "match this OR that, BUT ALSO not this" = `(Group1 OR) AND (Group2 AND NOT)`.

### Consistent Patterns

- All DB access goes through `get_connection(db_path)` from `db.py`.
- Every page section has a corresponding `load<PageName>()` function in `app.js` called from `navigate()`.
- Toast notifications use `toast(msg, type, duration)` — types: `'success'`, `'error'`, `'info'`.
- API calls from the frontend use the `api(method, path, body)` helper which wraps fetch and throws on non-2xx.
- Background jobs write to `normalization_jobs` for progress tracking.
- `esc(str)` is used throughout `app.js` to HTML-encode user data before inserting into innerHTML.
- **`INCOME_FILTER`** constant in `utils/query_helpers.py` defines the canonical income SQL condition: `amount > 0 AND statement_type = 'bank'`. All income queries must import and use this constant (or reference it in a comment when table aliases prevent direct use). CC positive amounts (payments, refunds) are never income. See BUG-6/7/8 history. A tripwire test (`test_income_filter_constant_unchanged`) guards against accidental changes.
- **Collapsible card panels**: Cards on Merchants and Categories pages use `.card-header-toggle` + `.card-collapsible-body` pattern. `toggleCardCollapse()` toggles `.collapsed` class and persists state in localStorage (`collapse_<cardId>`). Badge counts (`.badge-count`) show item totals even when collapsed. `ensureCardExpanded(cardId)` auto-opens a panel before scrolling to its content (e.g., when opening a form). Suggestion lists use `.suggestions-scroll` (max-height 400px), rule tables use `.rules-table-scroll` (max-height 450px). Note: localStorage is used for collapse state (alongside dark mode, colorblind palette, and onboarding prefs). If a DB-backed settings store is added later, consider migrating these UI prefs for cross-device consistency.
- **Category drill-down pattern**: `openCategoryDrilldown(categoryParent, dateFrom, dateTo)` opens a modal listing transactions for the given category within the date range. If `dateFrom`/`dateTo` are omitted, defaults to dashboard's current month. Used in: Dashboard top categories, Cash Flow spending breakdown, Monthly Summary top categories, Reports category tables. NOT applied to: Budget Tracker, Utilities Category List, Rule editors. "View All in Transactions" navigates to Bank tab with category + dates pre-filtered.
- **`evaluate_rule_groups(groups, text, compiled_regexes)`** in `utils/query_helpers.py` is the shared grouped boolean condition evaluator. All groups must pass (implicit AND). Within each group, conditions combined by `group_logic` (AND|OR). Supports match types: `exact`, `contains`, `starts_with`, `startswith`, `regex`. Used by `merchant_rules.CompiledRule.matches()` and `category_rules.normalize_category()`. Single implementation, two consumers — no duplicated logic.
- **Rule table search**: Merchant and Category rule tables have inline search bars. JS-only filtering (`filterMerchantRules()`, `filterCatRules()`) against cached `_allMerchantRules`/`_allCatRules` arrays. Case-insensitive match across all visible columns. Shows "X of N rules" count. Escape key clears filter. Search does NOT steal focus on load.
- **`openCategoryPicker(targetElement, options)`** is the single shared inline category picker used by all category-editing surfaces. Options: `{ currentCategory, onSave(category), onRemove(), allowRemove, placeholder }`. Internally uses `_ensureCategoryTaxonomy()` to cache the full category list from `GET /utilities/categories`. Renders a type-ahead dropdown at the target element position with "Parent > Subcategory" format. Escape key and click-outside cancel. Consumers: transaction row inline edit (`inlineCategoryEdit`), Utilities Merchant List inline edit (`_utilMerchCatClick`), Utilities bulk assign (`_utilMerchBulkAssignCat`), categorized merchant edit (`_editCategorizedMerchant`). **⚠️ AUDIT-1: A second implementation `_buildCategoryPickerHTML()` (line 6930) still exists**, used by uncategorized merchants panel (line 3491) and merchant category suggestions (line 3729). Consolidation needed — see BUG-18.
- **`category_override` pattern**: When a user manually edits a transaction's category (via inline edit), the `category_override` flag is set to TRUE. The batch `apply_category_rules()` job and `renormalize_merchant()` both filter with `WHERE COALESCE(category_override, FALSE) = FALSE`, skipping overridden rows. Users can reset the override via the "edited" badge, which sets `category_override=FALSE` and makes the row eligible for normalization again.
- **Merchant List category edits** ALWAYS target `merchant_category_map` and re-normalize all merchant transactions immediately via `renormalize_merchant()`. Never write `category_normalized` directly to `transactions_norm` from the Merchant List. **⚠️ AUDIT-1: `assign_category()` in `merchant_rules.py` actually DOES backfill `transactions_norm.category` directly (line 196-198)** despite this doc saying it doesn't — it writes both `merchant_category_map` AND `transactions_norm.category`. `renormalize_merchant()` is the targeted single-merchant re-normalizer that respects `category_override`. `POST /normalize/apply` accepts optional `merchant_filter` body param for targeted runs. Orphan categories (stale `category_normalized` not matching `merchant_category_map`) are detected by `GET /utilities/health` and fixed via full `POST /normalize/apply`.
- **`resolveTransactionTab(transactions)`** derives the correct destination tab (`'credit_card'` or `'bank'`) from the `statement_type` field of fetched transaction data. Use for all navigation from mixed-context views (dashboard drill-down, reports, utilities). Never hardcode destination tab where transaction data is available. Majority wins; tie defaults to `'credit_card'`. When both CC and bank transactions exist, show an info toast telling the user to switch tabs for the rest. Tab-specific contexts (CC filter bar, bank pagination) may hardcode their own tab.
- **Backup explicit column list policy**: `_TABLE_COLUMNS` in `api.py` maps table names to explicit SELECT column lists for backup export. Only `transactions_norm` currently needs this (26 columns, 11 from migrations). Other tables without migration-added columns continue using `SELECT *`. When adding migration columns to `transactions_norm`, update both `_TABLE_COLUMNS` and the restore INSERT statement.
- **Docker BuildKit cache corruption**: If Docker build fails with `parent snapshot does not exist` or similar layer cache errors, run `docker builder prune --all --force` before investigating code. Cache corruption from failed builds is a known Docker BuildKit issue and is not always a code problem.
- **Dark mode implementation**: Uses `[data-theme="dark"]` attribute on `<html>`, toggled via `toggleTheme()` in sidebar header. Persisted to `localStorage('spendly-theme')`. Initialized on page load via IIFE `_initTheme()` before first render. 11 of 19 root CSS variables have dark overrides. Accent colors (`--primary`, `--success`, `--danger`, `--warning`, `--staged`) intentionally keep their light-mode values (readable on dark backgrounds). Approximately 15 hardcoded color values remain in minor elements (file chip states, run status badges, alert banners) — these have dark-specific overrides via `[data-theme="dark"] .class` rules. Remaining hardcoded inline styles in app.js (e.g., inline `style="color:#22c55e"` for status colors) are impractical to convert to CSS variables without major refactoring — a future sprint could address these via data attributes or class-based styling.

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

**Current Version:** v2.25.1
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
| v2.6.0 | 2026-03-10 | Sprint 5 — Transaction Tagging: custom tags with name/color, many-to-many tag assignment per transaction, tag filtering in CC/Bank views, per-tag totals in Settings, tag popup UI, backup/restore support for tags; new `tags`, `transaction_tags` tables; new `GET/POST/PUT/DELETE /tags`, `POST/DELETE /transactions/tags`, `GET /transactions/{fp}/tags`, `GET /tags/totals` endpoints |
| v2.7.0 | 2026-03-10 | Sprint 6 — Savings Goals Tracker: create goals with name/target/date/account, progress bar UI, manual progress updates (set or add), auto-calculated monthly savings needed, suggested monthly savings from avg net cash flow, dashboard widget with inline CRUD; new `savings_goals` table; new `GET/POST/PUT/DELETE /savings-goals`, `POST /savings-goals/{id}/update-progress`, `GET /savings-goals/suggestions` endpoints; backup/restore support |
| v2.8.0 | 2026-03-10 | Sprint 7 — Monthly Summary Engine: auto-generated plain-language monthly summaries with total spent/income/net, vs-prior-month delta, top 3 categories with deltas, top 3 merchants, biggest single transaction; modal viewer with month navigation, save/regenerate, browsable history of stored summaries; new `monthly_summaries` table; new `POST /monthly-summaries/generate`, `GET /monthly-summaries`, `GET /monthly-summaries/{year}/{month}`, `DELETE /monthly-summaries/{year}/{month}` endpoints; backup/restore support |
| v2.9.0 | 2026-03-10 | Sprint 8 — Merchant Intelligence: per-merchant analytics with total spend, monthly avg, transaction frequency, months active, last transaction date; 3-month trend indicator (increasing/decreasing/flat) with MoM %; accelerating spend flag (>20% MoM); mini sparkline bars; sort by total spend/frequency/recent/trend; search filter; KPI summary (total merchants, accelerating count); new `GET /merchant-analytics` endpoint |
| v2.10.0 | 2026-03-10 | Sprint 9 — Spending Alerts & Thresholds: per-category spending alerts derived from existing budget goals; alert banners at top of dashboard for categories at 80% (warning) and 100% (exceeded) of monthly budget; budget status overview card with green/yellow/red chips per category; color-coded status dots on budget tracker progress bars; dismissible alert banners; alerts auto-reset each month (spending is month-scoped); enhanced `GET /dashboard/summary` response with `spending_alerts` array |
| v2.11.0 | 2026-03-10 | Sprint 10 — Net Worth Snapshot: manual net worth tracker with account management (checking/savings/investment/credit card/loan/other); assets vs liabilities breakdown; point-in-time snapshots with history chart; dashboard widget showing current net worth with trend vs last snapshot; new `nw_accounts` and `nw_snapshots` tables; new `GET/POST/PUT/DELETE /net-worth/accounts`, `GET /net-worth/summary`, `GET/POST/DELETE /net-worth/snapshots` endpoints; backup/restore support |
| v2.12.0 | 2026-03-10 | Sprint 11 — Annual Year-in-Review Report: generate annual financial reports with total income/spent/net saved, top 5 categories and merchants, biggest and lightest months, month-by-month chart, recurring costs total; modal viewer with year navigation, save/regenerate, print/PDF export via browser print dialog; stored report history with browse/compare/delete; new `annual_reports` table; new `POST /annual-reports/generate`, `GET /annual-reports`, `GET /annual-reports/{year}`, `DELETE /annual-reports/{year}` endpoints; backup/restore support |
| v2.13.0 | 2026-03-10 | Sprint 12 — Power User & Polish: keyboard shortcuts (j/k navigate, r review, c category edit, x select, / search, ? help, 1-9 tabs); inline category editing via double-click on transaction rows; bulk actions with multi-select checkboxes (mark reviewed, assign category, assign tag); colorblind-accessible palette (deuteranopia/protanopia safe); dark/light mode toggle with localStorage persistence; onboarding flow for first-time users (3-step guided import → categories → budgets); no new API endpoints — all features are UI-only |
| v2.13.1 | 2026-03-10 | Fix BUG-6/7/8: income classification — CC payments and refunds no longer counted as income; all income queries now require `amount > 0 AND statement_type = 'bank'`; applied to Monthly Summary, Annual Report, Cash Flow, transaction totals, tag totals, and analytics CSV reports; 3 regression tests added |
| v2.13.2 | 2026-03-10 | Centralized income filter constant (`INCOME_FILTER` in `utils/query_helpers.py`); replaced all 10 inline income conditions with constant reference; added custom report builder regression test and tripwire test for constant integrity; 264 total tests |
| v2.14.0 | 2026-03-10 | Collapsible panels + scroll containers on Merchants and Categories pages; each card panel gets expand/collapse toggle with item count badges; suggestion lists and rule tables capped with `max-height` + `overflow-y: auto`; collapse state persisted in localStorage; auto-expand on form open; responsive breakpoint for narrow viewports |
| v2.15.0 | 2026-03-10 | Global transaction search + dashboard category drill-down; new `GET /transactions/search` endpoint with text and amount operators (>, <, range); persistent search bar in topbar visible on all pages; `/` shortcut focuses search; floating results panel with keyboard nav (↑↓ Enter Esc); click result navigates to CC/Bank tab with date pre-filtered and transaction highlighted; dashboard top-categories bar chart rows are now clickable — opens drill-down modal showing all transactions for that category + month with subtotal; "View All in Transactions" navigates to Bank tab with category pre-filtered; new `category_parent` filter on `GET /transactions` |
| v2.16.0 | 2026-03-10 | Transaction Notes + Split Transactions; per-transaction `notes` TEXT field with inline popup editor (pencil icon, auto-save on Enter); new `PATCH /transactions/{fingerprint}` endpoint for notes updates; split transactions: `POST /transactions/{fingerprint}/split` divides one transaction into N sub-rows with category/amount/description; amounts validated to sum to parent; parent marked `is_split=TRUE` and excluded from all totals/queries via `_build_txn_where`; `DELETE /transactions/{fingerprint}/split` unsplits (removes children, restores parent); split children show "split" badge on description; split modal UI with dynamic row editor and remaining-amount tracker; new columns: `notes`, `is_split`, `split_parent_fingerprint` on `transactions_norm`; backup/restore updated for all 3 new columns |
| v2.17.0 | 2026-03-10 | Duplicate detection + Utilities tab + category picker fix; near-duplicate detection runs automatically after every import commit — flags transactions with same merchant, amount within 1%, date within 3 days; results stored in new `duplicate_candidates` table; non-blocking banner shown post-import linking to Duplicate Review; new Utilities tab with 5 collapsible sections: Category List (searchable taxonomy with counts), Merchant List (sortable with inline category edit), Rule Tester (full classification trace), Duplicate Review (side-by-side comparison with resolve actions), Data Health (5 quality metrics with navigation links); structured category picker replaces free-text input in Uncategorized Merchants with type-ahead dropdown from taxonomy + custom option; new `GET /duplicates`, `POST /duplicates/{id}/resolve`, `GET /utilities/categories`, `GET /utilities/merchants`, `POST /utilities/test-rule`, `GET /utilities/health` endpoints; backup/restore updated for `duplicate_candidates` table |
| v2.17.1 | 2026-03-10 | Fixed restore connection conflict introduced by Sprint C; all Sprint C connection sites now use try/finally guard pattern; added restore lock (HTTP 409 when background jobs active); `_restore_in_progress` flag prevents concurrent restores; 3 new backup/restore tests |
| v2.17.2 | 2026-03-10 | Fixed Utilities category list column name mismatch; `GET /utilities/categories` query used `normalized_category`/`parent_category` instead of correct `category`/`parent` from `category_rules` schema; audited merchants and health endpoints (no issues); added utility endpoint test |
| v2.17.3 | 2026-03-10 | Fixed Docker build cache corruption after category list fix; verified clean build — no code changes needed; issue was Docker BuildKit layer cache corruption, not a dependency or packaging problem; added Docker cache troubleshooting note to architectural decisions |
| v2.18.0 | 2026-03-10 | Merchant rule grouped boolean logic — implicit AND between groups; rules now support 1+ condition groups each with own AND/OR combiner; inter-group logic always AND; legacy flat conditions auto-migrate to single group on read; rule editor UI shows visually separated group blocks with per-group logic selector; matching engine evaluates groups independently then ANDs results; 6 new unit tests including Amazon-not-Prime example; conditions JSON schema updated to grouped format |
| v2.18.1 | 2026-03-10 | Fixed dashboard error loading (undefined values for `category_parent`/`total_amount`/`prev_spend`/`pct_change`); fixed analytics reports empty after backup restore — restore now auto-regenerates reports; new `POST /reports/regenerate` endpoint |
| v2.19.0 | 2026-03-10 | Year filter for transactions + cash flow — new `GET /transactions/years` endpoint; year dropdown on CC and Bank filter bars scopes Quick Date presets to selected year; cash flow period dropdown includes per-year options; clickable category drill-down app-wide — category rows in Cash Flow spending breakdown, Monthly Summary top categories, and Reports category tables now open drill-down modal with date-scoped transaction list; `openCategoryDrilldown()` accepts optional date range for flexible reuse |
| v2.20.0 | 2026-03-10 | Rule search bars + category rule grouped condition builder + shared rule evaluation utility; inline search/filter on Merchant and Category rule tables (real-time, case-insensitive, match count, Escape to clear); category rule editor replaced with grouped condition builder (exact/contains/starts_with match types, AND/OR groups, NOT support); backward-compatible with legacy exact-match rules; `evaluate_rule_groups()` shared utility in `query_helpers.py` used by both merchant and category rule engines; new `conditions` column on `category_rules` table; 7 new unit tests for shared utility; 281 total tests |
| v2.21.0 | 2026-03-10 | Suggested category edit + category rule test + retention features; editable category picker dropdown on Suggested Merchant Categories rows (searchable, pre-filled with suggestion, Accept/Accept All respects user changes); Test Conditions button on Category Rule Editor with inline test panel + new `POST /category-rules/test` endpoint (match result + live transaction count); Smart Unreviewed Nudge widget on Dashboard (shows when >5 unreviewed, progressive tone, dismiss options: tomorrow/next week/never via localStorage, estimated review time); Weekly Spending Recap banner on Mondays before 6pm (total spend, txn count, top category, See Details links to filtered transactions, dismissible per week); Budget Pace Indicator per budget row (projected end-of-month spend, color-coded green/yellow/red, only after day 5); new `GET /dashboard/weekly-recap` endpoint; 281 total tests |
| v2.22.0 | 2026-03-10 | Fixed bulk action bar visibility + added bulk assign merchant + selected row highlight; bulk bar buttons now use semi-transparent white styling (rgba backgrounds, white text/borders) instead of btn-secondary which was invisible against blue bar; full button set: Assign Category, Mark Reviewed, Exclude, Assign Merchant, Assign Tag, Clear Selection; selected rows get left border accent + light blue background tint (works in dark mode); Assign Merchant opens inline panel with debounced type-ahead merchant search (frequency-ordered); bulk merchant assign auto-applies category if merchant→category mapping exists; fixed bulkAssignCategory to use PATCH /transactions/{fp} instead of wrong /merchant-categories endpoint; extended PATCH /transactions/{fp} to accept category_normalized and excluded fields; new `PATCH /transactions/bulk-assign-merchant` and `GET /merchants/search` endpoints; 5 new tests; 286 total tests |
| v2.23.0 | 2026-03-10 | Restore modal UI fix + transaction empty filters + dark mode audit and fix; restore preview modal now has opaque backdrop (rgba 0.65 + blur), proper CSS classes instead of inline styles, warning text in styled warning box with red left border, alternating table rows, zero-value rows muted, clear content hierarchy with divider above action buttons; new "No Merchant" and "No Category" filter toggles on both CC and Bank transaction pages (independent, combinable, with Show only: label group); `GET /transactions` and `/transactions/totals` now accept `no_merchant` and `no_category` query params; dark mode audit: approach is `[data-theme="dark"]` attribute toggle (partially implemented, 11/19 root vars overridden); fixed 10+ hardcoded background colors to use CSS variables (`--bg-alt`, `--card-bg`, `--border`); added 20+ new dark mode rules for restore modal, wizard modal, file chips, run status badges, category picker, source dropdown, report cards, inline edit inputs, onboarding overlay; added `--bg-alt` to `:root`; 286 total tests |
| v2.23.1 | 2026-03-10 | Fix BUG-11: replaced all 5 `SELECT changes()` SQLite-only function calls with DuckDB-compatible patterns (COUNT queries, existence checks, pre-insert dedup); affected endpoints: mark-reviewed, mark-all-reviewed, patch transaction, unsplit, load.py row insert; critical fix — bulk operations were silently failing |
| v2.23.2 | 2026-03-10 | Fix BUG-12: backup/restore now uses explicit column list for `transactions_norm` (26 columns) via `_TABLE_COLUMNS` dict instead of `SELECT *`; restore INSERT updated to include `category_override`; prevents silent data loss when migration columns are added |
| v2.24.0 | 2026-03-10 | Category override + shared category picker + inline editing sprint; new `category_override` BOOLEAN column on `transactions_norm` (migration); `apply_category_rules()` skips override rows; shared `openCategoryPicker()` component replaces all previous category edit implementations; transaction row inline category edit with override badge ("edited" pill), click-to-reset, "Fix for All?" merchant prompt; Utilities Merchant List bulk select with Assign Category / Remove Category actions; Merchants tab "Show categorized merchants too" toggle with inline edit; `GET /merchant-categories` and `DELETE /merchant-categories/{merchant}` now used by frontend; 9 new tests (3 files); 294 total tests |
| v2.24.1 | 2026-03-10 | Fixed static sidebar version — now reads dynamically from pyproject.toml via GET /version; pyproject.toml version synced to v2.24.1 (was stuck at 2.0.0 since initial release); 2 new version endpoint tests; 296 total tests |
| v2.24.2 | 2026-03-10 | Fixed View All in Transactions tab routing — destination derived from statement_type data via `resolveTransactionTab()`; mixed-source categories show info toast; tie defaults to credit_card; audited all navigate/loadTxnTab calls — 2 Data Health links filed as follow-up bugs (BUG-14/15); 5 new tab routing tests; 301 total tests |
| v2.25.1 | 2026-03-10 | Audit 1 — Codebase vs PROJECT.md reality check: documented 5 new bugs (BUG-16 through BUG-20), identified 4 dead JS functions, 6 dead API endpoints, 2 dead Python functions, 7 dead CSS classes, 3 broken dark mode selectors, 2 undocumented API endpoints, 5 frontend status inaccuracies, 6 schema gaps, 2 duplicate category picker implementations; updated Feature Inventory, API Reference, and Known Issues sections |
| v2.25.0 | 2026-03-10 | Merchant List category edit now merchant-level only — all transactions updated atomically, no orphaned categories; `assign_category()` writes merchant_category_map only (no longer backfills transactions_norm.category directly); `renormalize_merchant()` re-normalizes all transactions for a single merchant respecting `category_override`; `POST /normalize/apply` supports optional `merchant_filter` for targeted single-merchant re-normalization; `GET /utilities/merchants` query fixed to return one row per normalized merchant with category from `merchant_category_map` JOIN; `GET /utilities/health` includes `orphaned_categories` metric with Fix Now button; bulk assign/remove operations run sequentially with re-normalization per merchant; `DELETE /merchant-categories/{merchant}` triggers re-normalization; 6 new tests; 307 total tests |

### Version Increment Rules

Every commit that changes functionality MUST update this table.

Increment rules:
- Patch (v2.1.0 → v2.1.1): bug fix, style change, doc update
- Minor (v2.1.0 → v2.2.0): new feature, new endpoint, new UI section
- Major (v2.1.0 → v3.0.0): breaking schema change, full rebuild, architecture overhaul

**pyproject.toml `version` MUST be incremented on every commit that touches `src/`, `web/`, or `tests/`.** The sidebar version display reads directly from this value via `GET /version` → `importlib.metadata.version("finance_etl")`. A static sidebar version means pyproject.toml was not updated. All three version sources must stay in sync: pyproject.toml, `GET /version` response, and PROJECT.md VERSION TRACKING current version.

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
| `POST` | `/wizard/validate` | wizard | Validate canonical field mapping | 🟡 Exists but unused by frontend (validates locally) |
| `POST` | `/wizard/save-and-run` | wizard | Save profile, start pipeline run | 🟢 Called |
| `GET` | `/wizard/profiles` | wizard | List all saved wizard profiles | 🟡 Exists but unused by frontend |
| `GET` | `/runs` | runs | List all import runs | 🟢 Called |
| `POST` | `/runs` | runs | Start a new pipeline run | 🟡 Exists but unused by frontend (wizard path used instead) |
| `GET` | `/runs/{run_id}` | runs | Get run status and counts | 🟢 Called |
| `GET` | `/runs/{run_id}/preview` | runs | Get staged rows for preview | 🟢 Called |
| `POST` | `/runs/{run_id}/commit` | runs | Commit staged run to ledger | 🟢 Called |
| `DELETE` | `/runs/{run_id}` | runs | Delete run (optionally preserve transactions) | 🟢 Called |
| `GET` | `/transactions/sources` | transactions | List available import sources per statement type | 🟢 Called |
| `GET` | `/transactions` | transactions | Query transactions with filters/grouping/sort/pagination (includes `category_parent`, `no_merchant`, `no_category` filters) | 🟢 Called |
| `GET` | `/transactions/search` | transactions | Global full-text search across description, merchant, amount, category; supports amount operators (`>`, `<`, range) | 🟢 Called |
| `GET` | `/transactions/totals` | transactions | Aggregate totals for filtered transactions | 🟢 Called |
| `GET` | `/transactions/unreviewed-count` | transactions | Count of all unreviewed transactions | 🟢 Called |
| `GET` | `/transactions/years` | transactions | List distinct years present in transaction data | 🟢 Called |
| `POST` | `/transactions/mark-reviewed` | transactions | Mark specific transactions as reviewed (by fingerprint) | 🟢 Called |
| `POST` | `/transactions/mark-all-reviewed` | transactions | Mark all filtered transactions as reviewed | 🟢 Called |
| `PATCH` | `/transactions/{fingerprint}` | transactions | Update transaction fields: `notes`, `category_normalized`, `category_parent`, `category_override`, `excluded` | 🟢 Called |
| `PATCH` | `/transactions/bulk-assign-merchant` | transactions | Assign merchant to multiple transactions; auto-applies category if mapping exists | 🟢 Called |
| `POST` | `/transactions/{fingerprint}/split` | transactions | Split a transaction into N sub-rows across categories | ⚠️ Backend exists but UI entry point missing |
| `DELETE` | `/transactions/{fingerprint}/split` | transactions | Unsplit: remove children and restore parent | ⚠️ Backend exists but UI entry point missing |
| `GET` | `/merchants/search` | merchant | Search distinct merchants by name (type-ahead, frequency-ordered) | 🟢 Called |
| `GET` | `/reports` | reports | List available analytics CSV reports | 🟢 Called |
| `GET` | `/reports/{name}` | reports | Download a report CSV | 🟢 Called |
| `POST` | `/reports/query` | reports | Run a custom parameterized report query | 🟢 Called |
| `GET` | `/charts/{name}` | reports | Get report as JSON for charting | 🟢 Called |
| `POST` | `/reports/regenerate` | reports | Re-generate all analytics CSV reports | 🟢 Called |
| `GET` | `/version` | ui | Get app version from pyproject.toml | 🟢 Called |
| `GET` | `/settings` | ui | Get current settings | 🟢 Called |
| `PATCH` | `/settings` | ui | Update settings | 🟢 Called |
| `GET` | `/logs` | ui | Get last N lines of latest log file | 🟢 Called |
| `GET` | `/logs/download` | ui | Download current log file | 🟡 Exists but unused by frontend |
| `GET` | `/metric-docs/{topic}` | ui | Inline metric documentation | 🟢 Called (opens in new tab) |
| `GET` | `/merchant-rules` | merchant | List all merchant normalization rules | 🟢 Called |
| `POST` | `/merchant-rules` | merchant | Create a merchant rule | 🟢 Called |
| `PUT` | `/merchant-rules/{id}` | merchant | Update a merchant rule | 🟢 Called |
| `DELETE` | `/merchant-rules/{id}` | merchant | Delete a merchant rule | 🟢 Called |
| `POST` | `/merchant-rules/test` | merchant | Test a rule against live descriptions | 🟢 Called |
| `GET` | `/merchant-rules/suggestions` | merchant | Suggest rules from unmatched descriptions | 🟢 Called |
| `GET` | `/merchant-categories` | merchant | List all merchant→category mappings | 🟢 Called (Merchants tab "Show categorized" toggle) |
| `GET` | `/merchant-categories/uncategorized` | merchant | List merchants without a category | 🟢 Called |
| `GET` | `/merchant-categories/suggestions` | merchant | Keyword-heuristic category suggestions for merchants | 🟢 Called |
| `POST` | `/merchant-categories` | merchant | Assign category to merchant | 🟢 Called |
| `DELETE` | `/merchant-categories/{merchant}` | merchant | Remove merchant category mapping | 🟢 Called (Utilities bulk remove, categorized merchant edit) |
| `POST` | `/normalize/apply` | merchant | Start batch merchant re-normalization job; optional `merchant_filter` body param for targeted single-merchant run | 🟢 Called |
| `GET` | `/normalize/{job_id}` | merchant | Poll normalization job status | 🟢 Called (merchant + category) |
| `GET` | `/category-rules` | categories | List all category rules | 🟢 Called |
| `POST` | `/category-rules` | categories | Create or update a category rule | 🟢 Called |
| `PUT` | `/category-rules/{id}` | categories | Update a category rule | 🟢 Called |
| `DELETE` | `/category-rules/{id}` | categories | Delete a category rule | 🟢 Called |
| `GET` | `/category-rules/unmapped` | categories | List unmapped raw categories with counts | 🟡 Exists but unused by frontend |
| `GET` | `/category-rules/suggestions` | categories | Suggest mappings using built-in taxonomy | 🟢 Called |
| `POST` | `/category-rules/test` | categories | Test grouped conditions against sample text + count matching live transactions | 🟢 Called |
| `POST` | `/category-rules/apply` | categories | Start category normalization background job | 🟢 Called |
| `GET` | `/budgets` | budgets | List all budget goals | 🟢 Called |
| `POST` | `/budgets` | budgets | Create or update a budget goal | 🟢 Called |
| `DELETE` | `/budgets/{id}` | budgets | Delete a budget goal | 🟢 Called |
| `GET` | `/budgets/rebalance` | budgets | Analyse avg spend vs budget, generate rebalance suggestions | 🟢 Called |
| `POST` | `/budgets/rebalance/apply` | budgets | Apply user-selected budget adjustments | 🟢 Called |
| `GET` | `/merchant-analytics` | merchant | Per-merchant spend, trends, frequency, acceleration flags | 🟢 Called |
| `GET` | `/dashboard/summary` | dashboard | MTD spend, top categories, budgets vs actual, spending alerts, net worth summary, recent transactions | 🟢 Called |
| `GET` | `/dashboard/weekly-recap` | dashboard | Weekly spending recap: total spend, txn count, top category for a given week | 🟢 Called |
| `GET` | `/cashflow/summary` | cashflow | Income vs spending vs net, monthly breakdown, category breakdown, MoM delta | 🟢 Called |
| `GET` | `/recurring` | recurring | Detect recurring transactions and return patterns + monthly total | 🟢 Called |
| `POST` | `/recurring/override` | recurring | Mark or unmark a merchant as recurring (user override) | 🟢 Called |
| `DELETE` | `/recurring/override/{merchant}` | recurring | Remove a recurring override | 🟡 Exists but unused by frontend (only in JS comment) |
| `GET` | `/backup/export` | backup | Export full state as v2 JSON (all 9 tables + wizard profiles) | 🟢 Called |
| `POST` | `/backup/restore` | backup | Restore from v1 or v2 JSON backup (auto-migrates, auto-snapshots) | 🟢 Called |
| `GET` | `/backup/status` | backup | Backup system status: last export, auto-backups list, table counts | 🟢 Called |
| `GET` | `/savings-goals` | savings | List all savings goals | 🟢 Called |
| `POST` | `/savings-goals` | savings | Create a savings goal | 🟢 Called |
| `PUT` | `/savings-goals/{id}` | savings | Update a savings goal | 🟢 Called |
| `DELETE` | `/savings-goals/{id}` | savings | Delete a savings goal | 🟢 Called |
| `POST` | `/savings-goals/{id}/update-progress` | savings | Add/set manual progress on a goal | 🟢 Called |
| `GET` | `/savings-goals/suggestions` | savings | Suggest monthly savings from avg net cash flow | 🟢 Called |
| `POST` | `/monthly-summaries/generate` | summaries | Generate or regenerate a monthly summary | 🟢 Called |
| `GET` | `/monthly-summaries` | summaries | List all stored monthly summaries | 🟢 Called |
| `GET` | `/monthly-summaries/{year}/{month}` | summaries | Get stored summary or generate on-the-fly | 🟢 Called |
| `DELETE` | `/monthly-summaries/{year}/{month}` | summaries | Delete a stored monthly summary | 🟢 Called |
| `POST` | `/annual-reports/generate` | annual-reports | Generate or regenerate an annual year-in-review report | 🟢 Called |
| `GET` | `/annual-reports` | annual-reports | List all stored annual reports | 🟢 Called |
| `GET` | `/annual-reports/{year}` | annual-reports | Get annual report (stored or on-the-fly) | 🟢 Called |
| `DELETE` | `/annual-reports/{year}` | annual-reports | Delete a stored annual report | 🟢 Called |
| `GET` | `/net-worth/accounts` | net-worth | List all net worth accounts | 🟢 Called |
| `POST` | `/net-worth/accounts` | net-worth | Create a net worth account | 🟢 Called |
| `PUT` | `/net-worth/accounts/{id}` | net-worth | Update a net worth account | 🟢 Called |
| `DELETE` | `/net-worth/accounts/{id}` | net-worth | Delete a net worth account | 🟢 Called |
| `GET` | `/net-worth/summary` | net-worth | Current net worth breakdown (assets, liabilities, net) | 🟡 Exists but unused by frontend |
| `POST` | `/net-worth/snapshots` | net-worth | Save point-in-time net worth snapshot | 🟢 Called |
| `GET` | `/net-worth/snapshots` | net-worth | List all net worth snapshots | 🟢 Called |
| `DELETE` | `/net-worth/snapshots/{id}` | net-worth | Delete a net worth snapshot | 🟢 Called |
| `GET` | `/` | ui | Serve web UI (index.html) | 🟢 Entry point |
| `GET` | `/docs` | (FastAPI auto) | Interactive API documentation | 🟢 Auto-generated |

~~**Frontend calls with no backend endpoint:** None — all previously broken references fixed.~~
