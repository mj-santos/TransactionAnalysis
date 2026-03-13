# finance_etl

> A fully local, privacy-first tool for importing, organising, and analysing bank and credit-card transaction CSVs — no cloud, no subscriptions, all data stays on your machine.

**Stack:** Python · DuckDB · Parquet · FastAPI · Vanilla JS

---

## What it does

1. **Import** — Upload any bank CSV export; a YAML mapping file tells the pipeline how to interpret each bank's columns
2. **Preview** — Review the parsed rows before they hit your ledger (optional but recommended)
3. **Commit** — Confirm to load the transactions permanently
4. **Analyse** — Five analytics reports are generated automatically: spend by category, cashflow, top merchants, and more
5. **Download** — Export any report as CSV or view it in the browser as a table

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

## First run: add a bank mapping

finance_etl needs to know which column in your bank's CSV is the date, which is the amount, etc. This is configured with a simple YAML file.

Two ready-to-use templates are included:

| Template | Format | Banks |
|---|---|---|
| `example_signed_amount.yaml` | Single `amount` column (positive = credit, negative = debit) | Chase, most US credit cards |
| `example_debit_credit.yaml` | Separate `debit` and `credit` columns | Many UK/EU banks |

**Copy and edit the one that matches your bank:**

```bash
# from your install directory:
cp config/mappings/example_signed_amount.yaml config/mappings/mybank.yaml
# then edit config/mappings/mybank.yaml with your bank's actual column names
```

See [`docs/CONFIG.md`](docs/CONFIG.md) for the full mapping reference and all available options.

---

## Using the web UI

Open **http://localhost:8000** in any browser.

| Tab | What you can do |
|---|---|
| **Import** | Upload a CSV, choose a bank mapping, preview rows, commit to ledger |
| **History** | Browse all past runs, view staged rows, commit or discard pending imports |
| **Reports** | View and download the 5 analytics reports as tables |

### Import flow (step by step)

1. Drag-and-drop your bank CSV onto the drop zone (or click to browse)
2. Select the bank mapping from the dropdown
3. Leave **Preview before committing** enabled (recommended)
4. Click **Start import** — the pipeline runs in the background
5. A progress indicator appears; when ready you'll see a table of parsed rows
6. Review the rows, then click **Commit to ledger** to save permanently — or **Discard** to cancel

For a detailed walkthrough with screenshots, see [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

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

View them in the **Reports** tab, or download as CSV files.

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

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Upload a CSV file |
| `GET` | `/mappings` | List available bank mappings |
| `GET` | `/runs` | List all import runs |
| `POST` | `/runs` | Start an import run (async) |
| `GET` | `/runs/{id}` | Poll run status + row counts |
| `GET` | `/runs/{id}/preview` | Inspect staged rows before commit |
| `POST` | `/runs/{id}/commit` | Commit staged run to ledger |
| `GET` | `/reports` | List generated analytics reports |
| `GET` | `/reports/{name}` | Download a report as CSV |
| `GET` | `/charts/{name}` | Report data as JSON rows |

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
| [`docs/CONFIG.md`](docs/CONFIG.md) | Bank mapping YAML reference |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Tests, lint, local dev workflow |
| [`docs/architecture.md`](docs/architecture.md) | Pipeline architecture |
