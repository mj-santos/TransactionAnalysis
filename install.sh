#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# finance_etl (Spendly) — One-line installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mj-santos/TransactionAnalysis/main/install.sh | bash
#
# The entire body is wrapped in main() so bash parses everything
# into memory before execution — required for piped (curl|bash)
# installs where stdin is the script itself.
# ─────────────────────────────────────────────────────────────

main() {

set -eo pipefail
# Note: -u (nounset) intentionally omitted — bash 3.2 on macOS
# treats empty arrays (e.g. BASH_SOURCE when piped) as unbound
# and errors even with ${arr[0]:-default} fallback syntax.

# ── Colours ─────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[finance_etl]${RESET} $*"; }
success() { echo -e "${GREEN}[finance_etl]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[finance_etl]${RESET} $*"; }
err()     { echo -e "${RED}[finance_etl] ERROR:${RESET} $*" >&2; }
fatal()   { err "$@"; exit 1; }

# ── Error trap — print context on unexpected failures ───────
trap '_rc=$?; err "Unexpected failure at line ${LINENO:-?} (exit code ${_rc})."; err "Re-run with \"bash -x install.sh\" for full debug trace."; exit ${_rc}' ERR

# ── Banner + diagnostics ────────────────────────────────────
echo -e "\n${BOLD}finance_etl — Automated Installer${RESET}\n"

ARCH="$(uname -m 2>/dev/null || echo unknown)"
OS="$(uname -s 2>/dev/null || echo unknown)"
BASH_VER="${BASH_VERSION:-unknown}"
info "System: ${OS} | bash ${BASH_VER} | arch: ${ARCH}"

# ── Platform check ──────────────────────────────────────────
case "${OS}" in
  MINGW*|MSYS*|CYGWIN*)
    fatal "This installer requires a native Unix shell (Linux, macOS, or WSL2).\n  You appear to be running Git Bash / MSYS2 / Cygwin on Windows.\n\n  Option 1 — Install WSL2 and re-run from a WSL2 terminal:\n    https://learn.microsoft.com/en-us/windows/wsl/install\n\n  Option 2 — Use Docker Desktop directly (see README.md Options C or D)."
    ;;
esac

# ── Constants ───────────────────────────────────────────────
REPO_OWNER="mj-santos"
REPO_NAME="TransactionAnalysis"
IMAGE="ghcr.io/$(echo "${REPO_OWNER}" | tr '[:upper:]' '[:lower:]')/$(echo "${REPO_NAME}" | tr '[:upper:]' '[:lower:]'):latest"
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main"
DEFAULT_INSTALL_DIR="${HOME}/finance-etl"
API_PORT="${FINANCE_ETL_API_PORT:-8000}"
MAX_WAIT=60

# ── Step 1: Check Docker ───────────────────────────────────
info "Step 1/6: Checking Docker…"
if ! command -v docker &>/dev/null; then
  fatal "Docker is not installed.\n  Install it from https://docs.docker.com/get-docker/ and re-run this installer."
fi
if ! docker info >/dev/null 2>&1; then
  fatal "Docker daemon is not running.\n  Open Docker Desktop (or start the daemon) and re-run this installer."
fi

COMPOSE=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE="docker-compose"
else
  fatal "docker compose is not available.\n  Upgrade Docker Desktop (v2.2+) or install the Compose plugin:\n  https://docs.docker.com/compose/install/"
fi

info "  Docker OK — compose: ${COMPOSE}, arch: ${ARCH}"

# ── Step 2: Determine install directory ─────────────────────
info "Step 2/6: Preparing install directory…"

# When piped (curl|bash), BASH_SOURCE is empty — fall back to $0
_self="${0:-bash}"
if [ -n "${BASH_SOURCE+x}" ] && [ "${#BASH_SOURCE[@]}" -gt 0 ]; then
  _self="${BASH_SOURCE[0]}"
fi

SCRIPT_DIR="$(cd "$(dirname "${_self}")" 2>/dev/null && pwd || echo "")"
if [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/Dockerfile" ] && [ -d "${SCRIPT_DIR}/src" ] && [ -f "${SCRIPT_DIR}/pyproject.toml" ]; then
  INSTALL_DIR="${SCRIPT_DIR}"
  BUILD_LOCAL=true
  info "  Detected full repo clone at: ${INSTALL_DIR}"
else
  INSTALL_DIR="${DEFAULT_INSTALL_DIR}"
  BUILD_LOCAL=false
  info "  Installing to: ${INSTALL_DIR}"
fi

mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}" || fatal "Cannot cd to ${INSTALL_DIR}"

# ── Step 3: Download config files (remote install) ──────────
info "Step 3/6: Downloading configuration…"

COMPOSE_FILE="docker-compose.yml"

if [ "${BUILD_LOCAL}" = false ]; then
  if [ ! -f ".env.example" ]; then
    info "  Downloading .env.example…"
    if ! curl -fsSL "${RAW_BASE}/.env.example" -o .env.example; then
      fatal "Failed to download .env.example from:\n  ${RAW_BASE}/.env.example\n  Check your internet connection and that the repository is accessible."
    fi
  fi
  if [ ! -d "config/mappings" ]; then
    info "  Downloading example mapping configs…"
    mkdir -p config/mappings
    if ! curl -fsSL "${RAW_BASE}/config/mappings/example_signed_amount.yaml" -o config/mappings/example_signed_amount.yaml; then
      fatal "Failed to download example_signed_amount.yaml.\n  Check your internet connection."
    fi
    if ! curl -fsSL "${RAW_BASE}/config/mappings/example_debit_credit.yaml" -o config/mappings/example_debit_credit.yaml; then
      fatal "Failed to download example_debit_credit.yaml.\n  Check your internet connection."
    fi
  fi

  COMPOSE_FILE="docker-compose.installer.yml"
  cat > "${COMPOSE_FILE}" <<YAML
services:
  finance-etl-api:
    image: ${IMAGE}
    container_name: finance-etl-api
    command: sh -c "finance_etl api --host \${FINANCE_ETL_API_HOST:-0.0.0.0} --port \${FINANCE_ETL_API_PORT:-8000} --db data/db/finance.duckdb --mappings-dir config/mappings --reports-dir data/reports"
    ports:
      - "\${FINANCE_ETL_API_PORT:-8000}:\${FINANCE_ETL_API_PORT:-8000}"
    environment:
      - FINANCE_ETL_API_HOST=\${FINANCE_ETL_API_HOST:-0.0.0.0}
      - FINANCE_ETL_API_PORT=\${FINANCE_ETL_API_PORT:-8000}
      - FINANCE_ETL_UI_PORT=\${FINANCE_ETL_UI_PORT:-3000}
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:\${FINANCE_ETL_API_PORT:-8000}/reports', timeout=2)\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    restart: unless-stopped
YAML
  info "  Generated ${COMPOSE_FILE}"
else
  info "  Using local docker-compose.yml"
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  info "  Created .env from .env.example (edit it to change ports)"
else
  info "  .env already exists — skipping"
fi

# Source .env for port overrides (< /dev/null prevents stdin consumption)
if [ -f ".env" ]; then
  set -o allexport
  # shellcheck disable=SC1091
  source .env < /dev/null 2>&1 || warn "  .env has syntax issues — using defaults"
  set +o allexport
fi
API_PORT="${FINANCE_ETL_API_PORT:-8000}"

# ── Step 4: Create data directories ─────────────────────────
info "Step 4/6: Creating data directories…"
for d in data/db data/raw data/uploads data/reports data/master data/profiles data/validation data/logs data/auto_backups; do
  mkdir -p "${d}"
done
info "  Data directories ready"

# ── Step 5: Build / pull Docker image ───────────────────────
info "Step 5/6: Obtaining Docker image…"

if [ "${BUILD_LOCAL}" = true ]; then
  info "  Building Docker image from local source…"
  if ! ${COMPOSE} -f "${COMPOSE_FILE}" build --pull --no-cache; then
    fatal "Docker build failed.\n  Check the build output above for details.\n  Common fix: ensure Docker Desktop has enough memory (≥4 GB)."
  fi
else
  info "  Pulling Docker image: ${IMAGE}"
  PULL_ERR=""
  if ! PULL_ERR=$(${COMPOSE} -f "${COMPOSE_FILE}" pull 2>&1); then
    warn "  Image pull failed. Reason:"
    warn "  ${PULL_ERR}"

    if echo "${PULL_ERR}" | grep -qi "manifest unknown\|not found\|denied\|unauthorized"; then
      warn "  The pre-built image is not available on the container registry."
    elif echo "${PULL_ERR}" | grep -qi "no match.*platform\|platform.*mismatch"; then
      warn "  Image architecture mismatch (common on Apple Silicon M1/M2/M3)."
    fi

    warn "  Falling back to local build from source archive…"
    SRC_ARCHIVE="https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/main.tar.gz"
    SRC_DIR="${INSTALL_DIR}/.source-build"
    rm -rf "${SRC_DIR}"
    mkdir -p "${SRC_DIR}"

    info "  Downloading source from: ${SRC_ARCHIVE}"
    if ! curl -fSL "${SRC_ARCHIVE}" | tar -xz -C "${SRC_DIR}" --strip-components=1; then
      fatal "Failed to download or extract source archive.\n  URL: ${SRC_ARCHIVE}\n  Check your internet connection and that the repository is public."
    fi

    info "  Building Docker image from source (this may take a few minutes)…"
    if ! docker build -t "${IMAGE}" "${SRC_DIR}"; then
      fatal "Docker build from source failed.\n  Check the build output above for details.\n  Common fixes:\n    • Ensure Docker Desktop has enough memory (≥4 GB)\n    • Try: docker system prune -f  (frees disk space)"
    fi
    success "  Image built successfully from source."
  fi
fi

# ── Step 6: Start the service ───────────────────────────────
info "Step 6/6: Starting finance_etl service…"

# Check if port is already in use
if command -v lsof &>/dev/null && lsof -i ":${API_PORT}" >/dev/null 2>&1; then
  warn "  Port ${API_PORT} is already in use. The service may fail to start."
  warn "  To use a different port, edit ${INSTALL_DIR}/.env and change FINANCE_ETL_API_PORT."
fi

if ! ${COMPOSE} -f "${COMPOSE_FILE}" up -d --remove-orphans 2>&1; then
  fatal "Failed to start the service.\n  Try: ${COMPOSE} -f ${COMPOSE_FILE} logs  (to see container logs)"
fi

info "  Waiting for API to become ready (up to ${MAX_WAIT}s)…"
elapsed=0
while ! curl -sf "http://localhost:${API_PORT}/reports" >/dev/null 2>&1; do
  if [ "${elapsed}" -ge "${MAX_WAIT}" ]; then
    warn "  API did not respond within ${MAX_WAIT}s."
    warn "  This may be normal on first start — the database needs to initialize."
    warn "  Check logs:  ${COMPOSE} -f ${COMPOSE_FILE} logs -f"
    warn "  Check status: docker ps -a --filter name=finance-etl-api"
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

if curl -sf "http://localhost:${API_PORT}/reports" >/dev/null 2>&1; then
  success "  API is healthy!"
fi

# ── Done ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✓ finance_etl is running!${RESET}"
echo ""
echo -e "  ${BOLD}Web UI   ${RESET}→  http://localhost:${API_PORT}"
echo -e "  ${BOLD}API docs ${RESET}→  http://localhost:${API_PORT}/docs"
echo ""
echo -e "  ${BOLD}Useful commands:${RESET}"
echo -e "    ${COMPOSE} -f ${COMPOSE_FILE} logs -f          # stream logs"
echo -e "    ${COMPOSE} -f ${COMPOSE_FILE} down             # stop service"
echo -e "    ${COMPOSE} -f ${COMPOSE_FILE} pull && ${COMPOSE} -f ${COMPOSE_FILE} up -d   # update to latest"
echo ""
echo -e "  ${BOLD}Install directory:${RESET}  ${INSTALL_DIR}"
echo -e "  ${BOLD}Bank mappings:${RESET}      ${INSTALL_DIR}/config/mappings/"
echo ""

}

# Invoke main — by this point bash has read the entire script into memory.
main "$@"
