# INSTALL

Detailed installation options for `finance_etl`.

## Supported environments

| Platform | Install methods | Notes |
|---|---|---|
| Linux x86_64 (Ubuntu / Debian) | All (1–5) | **Primary** — recommended for servers and CI |
| Linux ARM64 (Raspberry Pi, etc.) | All (1–5) | Multi-arch Docker image included |
| macOS Intel | All (1–5) | Full dev and prod use |
| macOS Apple Silicon (M1/M2/M3/M4) | All (1–5) | Native ARM64 Docker image; automatic source build fallback |
| Windows 10/11 + WSL2 | All (1–5) | Run all commands inside a WSL2 terminal |
| Windows (PowerShell / CMD) | 3, 4 only | Docker Desktop required; bash scripts (1, 2) not supported |

> **Multi-arch Docker images:** The CI pipeline builds images for both `linux/amd64` and `linux/arm64`, so the image runs natively on Intel, AMD, and ARM (including Apple Silicon) without emulation.

## Requirements

- Docker 24+ with Compose plugin (all Docker install methods 1–4)
- Python 3.11+ and pip 23+ (local venv install only, method 5)

---

## Method 1 — One-liner (curl, no git)

The fastest way to get started. No git clone needed.

```bash
curl -fsSL https://raw.githubusercontent.com/mj-santos/TransactionAnalysis/main/install.sh | bash
```

> **Requires bash** — run from macOS Terminal, any Linux terminal, or WSL2 on Windows. Will not work in PowerShell, CMD, Git Bash, or MSYS2.

The script runs 6 steps with progress output:
1. Checks Docker is installed and running, detects `docker compose`
2. Creates `~/finance-etl/` with all required directories
3. Downloads `.env.example` and example mapping configs from GitHub
4. Creates data directories (`data/db`, `data/raw`, `data/uploads`, etc.)
5. Pulls the pre-built Docker image from `ghcr.io`; if pull fails (architecture mismatch, image not published), automatically falls back to downloading and building from source
6. Starts the service and waits for it to become healthy

If anything fails, the script prints the error with context (line number, exit code) and suggests running `bash -x install.sh` for a full debug trace.

Open `http://localhost:8000` when the script finishes.

---

## Method 2 — Clone and run

```bash
git clone --depth 1 https://github.com/mj-santos/TransactionAnalysis.git finance-etl
cd finance-etl
bash install.sh
```

The install script detects the repo clone and builds the image locally instead of pulling from the registry.

> **Tip:** Use `bash install.sh` (not `./install.sh`) to avoid "permission denied" errors without needing `chmod +x`.

---

## Method 3 — Docker run (single command)

Pull and run the pre-built image directly:

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

> **Windows PowerShell:** Replace `$PWD` with `${PWD}` and `~/finance-etl` with `$HOME/finance-etl`. Requires Docker Desktop.

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
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e .
finance_etl api
```

Verify install:

```bash
finance_etl --help
```

---

## Windows (WSL2) setup

To use bash-based install methods (1, 2) on Windows:

1. **Install WSL2** (one-time, requires admin):
   ```powershell
   wsl --install
   ```
   This installs Ubuntu by default. Restart when prompted.

2. **Install Docker Desktop** from https://docs.docker.com/desktop/install/windows-install/
   - During setup, enable **"Use WSL 2 based engine"**
   - In Docker Desktop → Settings → Resources → WSL Integration → enable your distro

3. **Open a WSL2 terminal** (search "Ubuntu" in Start menu) and run:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/mj-santos/TransactionAnalysis/main/install.sh | bash
   ```

4. Open `http://localhost:8000` in your Windows browser — WSL2 automatically forwards ports.

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

### Permission denied running install.sh
```bash
# Use bash directly instead of ./install.sh:
bash install.sh

# Or add execute permission:
chmod +x install.sh && ./install.sh
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
- `data/auto_backups`

### Port already in use
Edit `.env` and change `FINANCE_ETL_API_PORT`, then:
```bash
docker compose down && docker compose up -d
```

### Docker image pull fails on Apple Silicon (M1/M2/M3)
The install script automatically falls back to building from source if the pre-built image can't be pulled. This takes a few minutes but requires no user action. If the automatic fallback also fails, try:
```bash
# Free up Docker disk space:
docker system prune -f
# Ensure Docker Desktop has at least 4 GB memory (Settings → Resources)
```

### Docker command not found in WSL2
Docker Desktop must be installed on Windows (not inside WSL2) with WSL integration enabled:
1. Open Docker Desktop → Settings → Resources → WSL Integration
2. Enable your WSL2 distro (e.g., Ubuntu)
3. Restart your WSL2 terminal
