#!/usr/bin/env bash
# Wrapped in main() so the entire script is parsed before execution,
# making it safe to run via: curl -fsSL <url> | bash
main() {
set -euo pipefail

REPO_OWNER="mj-santos"
REPO_NAME="TransactionAnalysis"
IMAGE="ghcr.io/$(echo "${REPO_OWNER}" | tr '[:upper:]' '[:lower:]')/$(echo "${REPO_NAME}" | tr '[:upper:]' '[:lower:]'):latest"
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main"
DEFAULT_INSTALL_DIR="${HOME}/finance-etl"
API_PORT="${FINANCE_ETL_API_PORT:-8000}"
MAX_WAIT=60

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[finance_etl]${RESET} $*"; }
success() { echo -e "${GREEN}[finance_etl]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[finance_etl]${RESET} $*"; }
error()   { echo -e "${RED}[finance_etl] ERROR:${RESET} $*" >&2; exit 1; }

echo -e "\n${BOLD}finance_etl — Automated Installer${RESET}\n"

if ! command -v docker &>/dev/null; then
  error "Docker is not installed. Install it from https://docs.docker.com/get-docker/ and re-run."
fi
if ! docker info &>/dev/null; then
  error "Docker daemon is not running. Start Docker and re-run."
fi

if docker compose version &>/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE="docker-compose"
else
  error "docker compose is not available. Upgrade Docker Desktop or install the Compose plugin."
fi

ARCH="$(uname -m 2>/dev/null || echo unknown)"
info "Docker OK (compose: ${COMPOSE}, arch: ${ARCH})"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [[ -f "${SCRIPT_DIR}/Dockerfile" && -d "${SCRIPT_DIR}/src" && -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
  INSTALL_DIR="${SCRIPT_DIR}"
  BUILD_LOCAL=true
  info "Detected full repo clone at: ${INSTALL_DIR}"
else
  INSTALL_DIR="${DEFAULT_INSTALL_DIR}"
  BUILD_LOCAL=false
  info "Installing to: ${INSTALL_DIR}"
fi

mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

COMPOSE_FILE="docker-compose.yml"

if [[ "${BUILD_LOCAL}" == false ]]; then
  if [[ ! -f ".env.example" ]]; then
    info "Downloading .env.example…"
    curl -fsSL "${RAW_BASE}/.env.example" -o .env.example
  fi
  if [[ ! -d "config/mappings" ]]; then
    info "Downloading example mapping configs…"
    mkdir -p config/mappings
    curl -fsSL "${RAW_BASE}/config/mappings/example_signed_amount.yaml" -o config/mappings/example_signed_amount.yaml
    curl -fsSL "${RAW_BASE}/config/mappings/example_debit_credit.yaml" -o config/mappings/example_debit_credit.yaml
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
fi

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  info "Created .env from .env.example (edit it to change ports)"
else
  info ".env already exists — skipping"
fi

set -o allexport
source .env < /dev/null 2>/dev/null || true
set +o allexport
API_PORT="${FINANCE_ETL_API_PORT:-8000}"

for d in data/db data/raw data/uploads data/reports data/master data/profiles data/validation data/logs data/auto_backups; do
  mkdir -p "${d}"
done
info "Data directories ready"

if [[ "${BUILD_LOCAL}" == true ]]; then
  info "Building Docker image from source…"
  ${COMPOSE} -f "${COMPOSE_FILE}" build --pull --no-cache
else
  info "Pulling Docker image ${IMAGE}…"
  if ! ${COMPOSE} -f "${COMPOSE_FILE}" pull 2>/dev/null; then
    warn "Pre-built image pull failed (often an architecture mismatch on Apple Silicon)."
    warn "Falling back to local build from source archive…"

    SRC_DIR="${INSTALL_DIR}/.source-build"
    rm -rf "${SRC_DIR}"
    mkdir -p "${SRC_DIR}"
    curl -fsSL "https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/main.tar.gz" | tar -xz -C "${SRC_DIR}" --strip-components=1
    docker build -t "${IMAGE}" "${SRC_DIR}"
  fi
fi

info "Starting finance_etl service…"
${COMPOSE} -f "${COMPOSE_FILE}" up -d --remove-orphans

info "Waiting for API to become ready (up to ${MAX_WAIT}s)…"
elapsed=0
until curl -sf "http://localhost:${API_PORT}/reports" >/dev/null 2>&1; do
  if (( elapsed >= MAX_WAIT )); then
    warn "API did not respond within ${MAX_WAIT}s."
    warn "Check logs with:  ${COMPOSE} -f ${COMPOSE_FILE} logs -f"
    break
  fi
  sleep 2
  (( elapsed += 2 ))
done

if curl -sf "http://localhost:${API_PORT}/reports" >/dev/null 2>&1; then
  success "API is healthy!"
fi

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
echo -e "  Add your bank mapping to:  ${INSTALL_DIR}/config/mappings/"
echo -e "  Copy an example:  cp config/mappings/example_signed_amount.yaml config/mappings/mybank.yaml"
echo ""
}

main "$@"
