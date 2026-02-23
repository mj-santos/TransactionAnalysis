# INSTALL

Detailed installation options for `finance_etl`.

## Supported environments

- **Primary:** Linux (Ubuntu/Debian)
- **Optional dev:** macOS (Intel + Apple Silicon)
- **Optional:** Windows via WSL2

## Requirements

- Docker 24+ with Compose plugin (all Docker install methods)
- Python 3.11+ and pip 23+ (local venv install only)

---

## Method 1 — One-liner (curl, no git)

The fastest way to get started. No git clone needed.

```bash
curl -fsSL https://raw.githubusercontent.com/mj-santos/TransactionAnalysis/main/install.sh | bash
```

The script:
1. Checks Docker is running
2. Creates `~/finance-etl/` with all required directories
3. Downloads `.env.example` and example mapping configs
4. Generates an installer Compose file (`docker-compose.installer.yml`) that uses the pre-built image
5. Copies `.env.example` → `.env`
6. Pulls the pre-built Docker image from `ghcr.io`
7. If pull fails (for example, architecture mismatch), it falls back to local source build automatically
8. Starts the service and waits for it to be healthy
9. Prints the URL

Open `http://localhost:8000` when the script finishes.

---

## Method 2 — Clone and run

```bash
git clone --depth 1 https://github.com/mj-santos/TransactionAnalysis.git finance-etl
cd finance-etl
./install.sh
```

The install script detects the repo clone and builds the image locally.

---

## Method 3 — Docker run (single command)

Pull and run the pre-built image directly, like Home Assistant:

```bash
docker run -d \
  --name finance-etl \
  --restart=unless-stopped \
  -p 8000:8000 \
  -v "$PWD/data:/app/data" \
  -v "$PWD/config:/app/config" \
  ghcr.io/mj-santos/transactionanalysis:latest \
  finance_etl api --host 0.0.0.0 --port 8000
```

Create your `config/mappings/` directory and add a mapping YAML before running.

---

## Method 4 — Docker Compose (recommended for persistence)

```bash
# Clone or download docker-compose.yml, then:
cp .env.example .env          # adjust ports if needed
docker compose up -d
```

Use compose when you want:
- Persistent `data/db` DuckDB file
- Persistent report and Parquet outputs
- Stable API + web UI endpoint
- Auto-restart on reboot (`restart: unless-stopped`)

---

## Method 5 — Local Python venv (development only)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
finance_etl api
```

Verify install:

```bash
finance_etl --help
```

---

## Ports and env vars

Defaults (override in `.env`):
- API + Web UI: `http://0.0.0.0:8000`

Available env vars:
- `FINANCE_ETL_API_HOST` (default `0.0.0.0`)
- `FINANCE_ETL_API_PORT` (default `8000`)
- `FINANCE_ETL_UI_PORT` (default `3000`, reserved for future standalone UI)

---

## After installing

1. Open the web UI at `http://localhost:8000`
2. Add your bank mapping to `config/mappings/mybank.yaml`
   ```bash
   cp config/mappings/example_signed_amount.yaml config/mappings/mybank.yaml
   # edit config/mappings/mybank.yaml with your bank's column names
   ```
3. Upload a CSV on the Import tab
4. Select your mapping, enable Preview, and click **Start import**

---

## Troubleshooting

### API is not responding
```bash
docker compose logs -f         # stream logs
docker compose ps              # check container status
```

### `ModuleNotFoundError: duckdb` (local venv)
```bash
pip install -e .
```

### Permission issues writing data
```bash
chmod -R 777 data/   # quick fix for local testing
```

Required writable directories:
- `data/db`
- `data/raw`
- `data/uploads`
- `data/reports`
- `data/master`
- `data/profiles`
- `data/validation`
- `data/logs`

### Port already in use
Edit `.env` and change `FINANCE_ETL_API_PORT`, then:
```bash
docker compose down && docker compose up -d
```
