# User Guide — finance_etl

This guide walks you through everything you need to go from a fresh install to viewing your first analytics report.

**Time required for first import:** ~10 minutes (mostly setup of your bank mapping).

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [Install (choose one method)](#2-install-choose-one-method)
3. [Open the web UI](#3-open-the-web-ui)
4. [Set up your bank mapping](#4-set-up-your-bank-mapping)
5. [Import your transactions](#5-import-your-transactions)
6. [Review the preview](#6-review-the-preview)
7. [View your reports](#7-view-your-reports)
8. [Import more data (subsequent runs)](#8-import-more-data-subsequent-runs)
9. [Troubleshooting](#9-troubleshooting)
10. [FAQ](#10-faq)

---

## 1. Prerequisites

### For Docker install (recommended)

- **Docker Desktop** (macOS / Windows) or **Docker Engine** (Linux)
  - Download: https://docs.docker.com/get-docker/
  - Minimum version: Docker 24+, Compose plugin included
- No Python needed

### For local Python install

- Python 3.11 or newer
- pip 23 or newer

---

## 2. Install (choose one method)

### Method 1 — One-liner (easiest, no git)

```bash
curl -fsSL https://raw.githubusercontent.com/mj-santos/TransactionAnalysis/main/install.sh | bash
```

This script:
- Checks Docker is running
- Creates `~/finance-etl/` with all required folders
- Pulls the pre-built Docker image
- Starts the service
- Waits until the API is healthy and prints the URL

Skip to [step 3](#3-open-the-web-ui).

---

### Method 2 — Clone and build

```bash
git clone --depth 1 https://github.com/mj-santos/TransactionAnalysis.git finance-etl
cd finance-etl
./install.sh
```

The script detects the full source tree and builds the image locally.

---

### Method 3 — Docker run (one command)

```bash
mkdir -p ~/finance-etl/{data,config/mappings}
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

---

### Method 4 — Docker Compose (persistent, recommended for home servers)

```bash
cp .env.example .env      # optional: edit to change ports
docker compose up -d
```

---

### Method 5 — Python venv (developers)

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e .
finance_etl api
```

---

## 3. Open the web UI

After any install method, open your browser and go to:

```
http://localhost:8000
```

You should see the finance_etl web interface with three tabs at the top:
**Import** · **History** · **Reports**

> If you get a "connection refused" error, wait a few seconds and refresh — the API may still be starting up. For Docker installs, run `docker compose logs -f` to check the logs.

---

## 4. Set up your bank mapping

finance_etl needs a **mapping file** to understand your bank's CSV format. This is a small YAML file that tells the pipeline:
- Which column is the transaction date
- Which column is the amount (and whether it's a single signed column or separate debit/credit columns)
- The date format your bank uses
- Your currency

### Step 1 — Export a CSV from your bank

Log into your bank's website and download a CSV of recent transactions. Keep it handy — you'll need to look at the column names.

### Step 2 — Open the CSV and note the column headers

Open the file in a text editor or spreadsheet app. The first row will be the headers, for example:

```
Transaction Date,Post Date,Description,Category,Amount
01/15/2024,01/16/2024,STARBUCKS #12345,,"-5.40"
01/14/2024,01/15/2024,DIRECT DEPOSIT,,"1234.56"
```

### Step 3 — Pick the right template

| If your bank CSV has… | Use this template |
|---|---|
| One `Amount` column (positive and negative numbers) | `example_signed_amount.yaml` |
| Separate `Debit` and `Credit` columns | `example_debit_credit.yaml` |

### Step 4 — Copy and edit the template

Navigate to your install directory (e.g. `~/finance-etl/` or the cloned repo):

```bash
cp config/mappings/example_signed_amount.yaml config/mappings/chase.yaml
```

Open `config/mappings/chase.yaml` in a text editor. The key fields to edit:

```yaml
bank_key: chase               # short identifier — no spaces
bank_name: "Chase"            # display name shown in the UI
account_name: "Freedom Card"  # your account name
account_id: "VISA-XXXX-1234"  # safe token, NOT your full card number

# Update these to match your actual CSV column headers:
column_map:
  "Transaction Date": transaction_date
  "Post Date": posted_date
  "Description": description
  "Amount": amount

date:
  transaction_date: "Transaction Date"
  posted_date: "Post Date"
  date_format: "%m/%d/%Y"   # US format: MM/DD/YYYY

amount:
  signed_amount: "Amount"   # the exact column name from your CSV

currency_default: "USD"
```

**Common date formats:**

| Bank date looks like | date_format value |
|---|---|
| `01/15/2024` | `%m/%d/%Y` |
| `15/01/2024` | `%d/%m/%Y` |
| `2024-01-15` | `%Y-%m-%d` |
| `Jan 15, 2024` | `%b %d, %Y` |
| `15 Jan 2024` | `%d %b %Y` |

> **Tip:** If you have multiple bank accounts, create one YAML file per account and name them clearly (e.g. `chase_freedom.yaml`, `chase_checking.yaml`, `bofa_savings.yaml`).

For the full mapping reference, see [`docs/CONFIG.md`](CONFIG.md).

---

## 5. Import your transactions

### Step 1 — Go to the Import tab

Click **Import** in the top navigation.

### Step 2 — Upload your CSV

Drag-and-drop your bank CSV onto the drop zone, or click **Choose file** to browse.

- The file is uploaded to the server's `data/uploads/` folder
- Filename is prefixed with a random ID to avoid conflicts
- Only the file path is stored — no parsing happens yet

### Step 3 — Select your bank mapping

A dropdown will appear listing all YAML files in `config/mappings/`. Select the one that matches your bank (e.g. "Chase").

If you don't see your mapping yet, add the YAML file to `config/mappings/` and reload the page.

### Step 4 — Enable Preview (recommended)

The **Preview before committing** toggle is on by default. Leave it enabled for your first import — it lets you verify the parsed rows before they're saved permanently.

### Step 5 — Click Start import

Click the **Start import** button. The pipeline runs in the background. A progress indicator will appear.

The pipeline does the following automatically:
1. **Ingest** — registers the file and detects encoding
2. **Profile** — summarises the raw columns
3. **Map** — applies your YAML mapping to rename and reformat columns
4. **Normalize** — standardises dates, amounts, and currencies
5. **Validate** — checks for parsing errors or missing fields
6. **Stage** — saves the validated rows to a staging area (if preview mode is on)

---

## 6. Review the preview

When the pipeline finishes, a table of parsed transactions appears on screen.

### What to check

- **Dates** look correct and are in the right order
- **Amounts** have the right sign (negative = money out, positive = money in)
- **Description** column is readable

### If everything looks good

Click **Commit to ledger** — the transactions are permanently saved and the analytics reports are generated.

### If something looks wrong

Click **Discard** — nothing is saved. Check your YAML mapping (usually a column name typo or the wrong date format) and try again.

### Common issues in preview

| Symptom | Fix |
|---|---|
| All amounts are the same sign | Check `amount_format_family`: use `signed` vs `debit_credit` |
| Dates are off by a month or day | Check `date_format` — make sure `%m` and `%d` are not swapped |
| Blank `description` column | Check `column_map` — the key must exactly match your CSV header |
| Extra columns with odd data | Add unwanted column names to `drop_columns` in your YAML |

---

## 7. View your reports

After a successful import, click the **Reports** tab.

You'll see up to five report cards:

| Report | What it shows |
|---|---|
| **spend_by_month_category** | How much you spent in each category per month |
| **cashflow_by_month** | Total income, total outflow, and net per month |
| **spend_by_merchant** | Total spent at each merchant across all time |
| **totals_by_account** | Net balance per account |
| **top_merchants** | Your top 50 merchants by total spend |

Click a report name to view it as a table in the browser.

Click **Download CSV** to save the raw data to your machine.

> **Note:** Reports are regenerated every time you commit a new import. They always reflect your full transaction history.

---

## 8. Import more data (subsequent runs)

To add more transactions later:

1. Export a new CSV from your bank (cover a new date range)
2. Go to the **Import** tab and repeat steps 2–6
3. The pipeline will only add transactions not already in the ledger (duplicates are detected by date + amount + description hash)

**Best practice:** export in overlapping date ranges (e.g. last 3 months each time) — duplicates are handled automatically.

---

## 9. Troubleshooting

### The page doesn't load at http://localhost:8000

```bash
# Check if the container is running
docker compose ps

# Stream logs
docker compose logs -f

# Or for docker run installs:
docker logs finance-etl -f
```

### Upload failed: Internal Server Error

- Confirm the container image was rebuilt after the latest changes:
  ```bash
  docker compose down
  docker compose build --no-cache
  docker compose up -d
  ```
- Confirm the `data/uploads/` directory is writable:
  ```bash
  chmod -R 777 data/
  ```

### No mappings appear in the dropdown

- Confirm your YAML files are in `config/mappings/`
- The mapping directory is mounted as `-v "$PWD/config:/app/config"` — check your `docker run` or `docker-compose.yml`
- YAML filenames must end in `.yaml` (not `.yml`)

### Import fails immediately

- Check `docker compose logs -f` for the error detail
- Common cause: column name in `column_map` doesn't exactly match the CSV header (check for trailing spaces)
- Verify the date format matches your CSV

### Port 8000 is already in use

Edit `.env` and change `FINANCE_ETL_API_PORT`, then restart:

```bash
docker compose down && docker compose up -d
```

Or use a different port with `docker run -p 9000:8000 ...`.

### Data directories: permission denied

```bash
chmod -R 777 data/
```

Required writable directories: `data/db`, `data/raw`, `data/uploads`, `data/reports`, `data/master`, `data/profiles`, `data/validation`, `data/logs`

---

## 10. FAQ

**Is my data sent anywhere?**
No. Everything runs locally. No network calls are made beyond pulling the Docker image on install. Your transaction data never leaves your machine.

**Can I import from multiple banks?**
Yes. Create one mapping YAML per bank/account. Each import run selects one mapping file. Run separate imports for each bank, and all transactions are merged into the same ledger.

**What CSV formats are supported?**
Any CSV dialect — comma, semicolon, tab-separated. Encoding is auto-detected (UTF-8, UTF-8 BOM, Latin-1, Windows-1252, etc.). The mapping file handles the column interpretation.

**Can I re-import the same file?**
Yes. Duplicate transactions (matched by date, amount, and description) are detected and skipped automatically. Re-importing the same file is safe.

**What happens if I click Discard on the preview?**
Nothing is saved to the ledger. The uploaded CSV file remains in `data/uploads/` but no transaction records are committed. You can fix your mapping and re-import.

**Can I delete transactions?**
Not through the UI currently. The DuckDB database file is at `data/db/finance.duckdb`. You can open it with DuckDB CLI or the Python SDK if you need to edit records manually.

**Where are my files stored?**
- Raw CSVs: `data/uploads/` and `data/raw/`
- Database: `data/db/finance.duckdb`
- Analytics reports: `data/reports/*.csv`
- Parquet exports: `data/master/`

**How do I back up my data?**
Copy the entire `data/` folder. The DuckDB file at `data/db/finance.duckdb` is the primary store.

**How do I update to a newer version?**
```bash
# Docker Compose
docker compose pull && docker compose up -d

# docker run
docker pull ghcr.io/mj-santos/transactionanalysis:latest
docker stop finance-etl && docker rm finance-etl
# re-run the original docker run command
```

**The API docs at /docs are empty — no schemas showing?**
This means the container is running an older image without the Pydantic models. Rebuild:
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

**I get "Run is not in staged state" when trying to commit**
This happens if the server was restarted between preview and commit (staged state is held in memory). Re-run the import and commit in the same session.

---

*For install options and port configuration, see [`docs/INSTALL.md`](INSTALL.md).*
*For the full bank mapping YAML reference, see [`docs/CONFIG.md`](CONFIG.md).*
