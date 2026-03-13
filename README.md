# Spendly (finance_etl)

> A fully local, privacy-first tool for importing, organising, and analysing bank and credit-card transaction CSVs — no cloud, no subscriptions, all data stays on your machine.

**Stack:** Python · DuckDB · Parquet · FastAPI · Vanilla JS

---

## What it does

1. **Import** — Upload any bank CSV; the built-in mapping wizard auto-detects your columns and date formats
2. **Preview** — Review parsed rows before they hit your ledger (recommended)
3. **Commit** — Confirm to load the transactions permanently
4. **Categorise** — Merchant normalization rules and category rules organise your data automatically
5. **Analyse** — Dashboard, cash flow charts, budget tracking, recurring charge detection, and downloadable reports

The web UI is built in and served by the same process — no separate install needed.

---

## Quick start (recommended — Docker)

> **Multi-arch images:** The Docker image is built for both `linux/amd64` (Intel/AMD) and `linux/arm64` (Apple Silicon, ARM servers), so it runs natively on all supported platforms.

### Option A — One-liner installer

No git required. Installs into `~/finance-etl/`, pulls the Docker image, and starts the service.

```bash
curl -fsSL https://raw.githubusercontent.com/mj-santos/TransactionAnalysis/main/install.sh | bash
```

> **Requires a Unix shell** — run this from macOS Terminal, any Linux terminal, or WSL2 on Windows. It will not work in PowerShell or CMD.

Open **http://localhost:8000** when the script finishes.

---

### Option B — Clone and build

```bash
git clone --depth 1 https://github.com/mj-santos/TransactionAnalysis.git finance-etl
cd finance-etl
./install.sh
```

The script detects the repo clone and builds the image locally.

---

### Option C — Docker run (single command)

```bash
mkdir -p ~/finance-etl/data ~/finance-etl/config/mappings
cd ~/finance-etl

docker run -d \
  --name finance-etl \
  --restart=unless-stopped \
  -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  -v "$PWD/config:/app/config" \
  ghcr.io/mj-santos/transactionanalysis:latest \
  finance_etl api --host 0.0.0.0 --port 8000
```

> **Windows (PowerShell):** Replace `$PWD` with `${PWD}` and `~/finance-etl` with `$HOME/finance-etl`. Requires Docker Desktop.

Open **http://localhost:8000**.

---

### Option D — Docker Compose

```bash
cp .env.example .env   # optional: change ports
docker compose up -d
```

Open **http://localhost:8000**.

---

### Option E — Python venv (development only)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e .
finance_etl api
```

---

## First run: importing your data

No manual configuration needed. The built-in **Mapping Wizard** handles everything:

1. Open **http://localhost:8000** and go to the **Import** tab
2. Drag-and-drop your bank CSV (or click to browse)
3. The wizard auto-detects your CSV columns, date format, and statement type (credit card or bank)
4. Review the suggested column mappings and adjust if needed
5. Click through to import — the wizard saves your mapping profile for next time

On subsequent imports from the same bank, the wizard recognises the file format and pre-fills all settings automatically.

> **Advanced users:** You can also create YAML mapping files manually in `config/mappings/`. See [`docs/CONFIG.md`](docs/CONFIG.md) for the full reference.

---

## Using the web UI

Open **http://localhost:8000** in any browser.

| Tab | What you can do |
|---|---|
| **Dashboard** | Monthly spend KPIs, top categories, budget tracker, savings goals, net worth, monthly summaries, year-in-review reports |
| **Import** | Upload CSVs via the mapping wizard, preview rows, commit to ledger |
| **History** | Browse past import runs, view staged rows, commit or discard pending imports |
| **Credit Cards** | Filter, sort, search, tag, split, and categorise credit card transactions |
| **Bank Transactions** | Same feature set for bank/debit transactions |
| **Cash Flow** | Income vs spending charts, monthly breakdown, category drilldown |
| **Reports** | View/download analytics reports, build custom reports with filters |
| **Merchants** | Merchant intelligence analytics, normalization rules, auto-fill unmatched |
| **Categories** | Category rule management, suggested mappings, apply normalization |
| **Recurring** | Auto-detected recurring charges, annual fee suggestions, pause/edit/delete |
| **Utilities** | Category list, merchant list, rule tester, duplicate review, data health |
| **Settings** | App settings, backup/restore, tag management, logs |

### Import flow (step by step)

1. Drag-and-drop your bank CSV onto the drop zone (or click to browse)
2. The mapping wizard opens automatically — it detects headers, date format, and amount style
3. Confirm the column mappings (auto-suggested) and statement type
4. Review the summary, then start the import
5. Preview the parsed rows in a table
6. Click **Commit to ledger** to save permanently — or **Discard** to cancel

After committing, the system automatically runs duplicate detection and generates analytics reports.

---

## Key features

- **Mapping Wizard** — auto-detects CSV columns, date formats, and amount styles; saves profiles per bank for instant re-import
- **Budget Tracker** — set monthly budgets per category with spending alerts at 80% and 100% thresholds; rebalance suggestions based on actual spending
- **Cash Flow Analysis** — income vs spending with monthly charts, category breakdown, and month-over-month deltas
- **Merchant Intelligence** — per-merchant spend analytics, 3-month trends, accelerating spend flags
- **Recurring Charge Detection** — auto-detects weekly/monthly/quarterly/annual patterns; annual fee keyword matching; pause/edit/delete
- **Transaction Tagging** — custom tags with colors, filterable across all transaction views
- **Split Transactions** — split one transaction into multiple categories
- **Duplicate Detection** — fingerprint-based exact dedup plus fuzzy matching for description drift and amount variance
- **Savings Goals** — track progress toward savings targets with suggested monthly amounts
- **Net Worth Tracking** — manual account balances with point-in-time snapshots and trend charts
- **Monthly Summaries & Year-in-Review** — auto-generated narrative reports with KPIs
- **Dark Mode & Colorblind Palette** — accessibility toggles in the sidebar
- **Keyboard Shortcuts** — `j`/`k` navigate, `r` review, `c` category edit, `/` search, `?` help
- **Full Backup/Restore** — JSON export of all data with auto-backup on every import

---

## Analytics reports

Generated automatically after every successful import.

| Report | Contents |
|---|---|
| `spend_by_month_category.csv` | Monthly spend broken down by category |
| `cashflow_by_month.csv` | Monthly total income, total outflow, and net |
| `spend_by_merchant.csv` | Total spent per merchant across all time |
| `totals_by_account.csv` | Net balance per account |
| `top_merchants.csv` | Top 50 merchants by total spend |

View them in the **Reports** tab, or download as CSV files. A custom report builder is also available for ad-hoc queries.

---

## Supported environments

| Platform | Install methods | Notes |
|---|---|---|
| Linux x86_64 (Ubuntu / Debian) | All (A–E) | **Primary** — recommended for servers and CI |
| Linux ARM64 (Raspberry Pi, etc.) | All (A–E) | Multi-arch Docker image included |
| macOS Intel | All (A–E) | Full dev and prod use |
| macOS Apple Silicon (M1/M2/M3/M4) | All (A–E) | Native ARM64 Docker image; automatic source build fallback |
| Windows 10/11 + WSL2 | A, B, C, D, E | Run bash commands inside a WSL2 terminal |
| Windows (PowerShell / CMD) | C, D only | Docker Desktop required; bash scripts (A, B) not supported |

**Requirements:**
- Docker 24+ with Compose plugin (for Docker install methods A–D)
- Python 3.11+ (for the venv install method E only)

---

## Changing the port

Edit `.env` (copy from `.env.example` if it doesn't exist):

```bash
FINANCE_ETL_API_PORT=9000
```

Then restart:

```bash
docker compose down && docker compose up -d
# or for docker run: stop the container and re-run with -p 9000:9000
```

---

## Updating to the latest version

```bash
# Docker Compose
docker compose pull && docker compose up -d

# docker run
docker pull ghcr.io/mj-santos/transactionanalysis:latest
docker stop finance-etl && docker rm finance-etl
# re-run the docker run command

# Git clone (rebuild)
git pull && ./install.sh
```

---

## API

Interactive docs: **http://localhost:8000/docs**

The API powers all web UI features. Key endpoint groups:

| Group | Endpoints | Description |
|---|---|---|
| Import | `/upload`, `/wizard/*`, `/runs/*` | CSV upload, mapping wizard, run management |
| Transactions | `/transactions/*` | Query, filter, search, edit, split, tag, review |
| Merchants | `/merchant-rules/*`, `/merchant-categories/*`, `/merchant-analytics` | Rules CRUD, category mapping, intelligence |
| Categories | `/category-rules/*` | Rules CRUD, suggestions, normalization |
| Normalization | `/normalize/*` | Background merchant/category normalization jobs |
| Reports | `/reports/*`, `/charts/*` | Analytics CSVs, custom queries, chart data |
| Dashboard | `/dashboard/*`, `/cashflow/*` | Summary KPIs, weekly recap, cash flow |
| Budgets | `/budgets/*` | Budget goals, rebalance suggestions |
| Recurring | `/recurring/*` | Detection, overrides, annual fee suggestions |
| Savings | `/savings-goals/*` | Goal CRUD, progress updates, suggestions |
| Net Worth | `/net-worth/*` | Account management, snapshots |
| Summaries | `/monthly-summaries/*`, `/annual-reports/*` | Generated narrative reports |
| Backup | `/backup/*` | Export/restore/status |
| Tags | `/tags/*`, `/transactions/tags` | Tag CRUD, assignment |
| Utilities | `/utilities/*`, `/duplicates/*` | Health checks, rule testing, duplicate review |

### Programmatic usage

```python
from finance_etl.pipeline import run_with_options, commit_run

# Preview first, then commit
result = run_with_options(
    inputs=["data/raw/transactions.csv"],
    mapping_path="config/mappings/mybank.yaml",
    db_path="data/db/finance.duckdb",
    preview_only=True,
)
# inspect result.run_id and result.counts …
commit_run(result.run_id)
```

---

## CLI reference

| Command | Description |
|---|---|
| `finance_etl api` | Start the API + web UI |
| `finance_etl run` | Full pipeline (non-interactive) |
| `finance_etl ingest` | Register and profile CSV files only |
| `finance_etl validate` | Print validation report |
| `finance_etl parquet --refresh` | Force Parquet refresh |
| `finance_etl analytics` | Export analytics CSVs |

---

## Documentation

| Document | What's in it |
|---|---|
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Step-by-step guide for new users (start here) |
| [`docs/INSTALL.md`](docs/INSTALL.md) | All install methods, ports, troubleshooting |
| [`docs/CONFIG.md`](docs/CONFIG.md) | Bank mapping YAML reference (advanced) |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Tests, lint, local dev workflow |
| [`docs/architecture.md`](docs/architecture.md) | Pipeline architecture |
