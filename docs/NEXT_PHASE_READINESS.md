# Next-phase readiness audit (Docker install + UI testing prep)

This audit verifies the repository is ready for the next phase: **easy Docker installation + UI testing**.

## What was re-verified

1. **Core regression suite**
   - `pytest -q` executed successfully (`92 passed`).
2. **Code-path continuity checks**
   - Stable pipeline API still present (`pipeline.run`, `run_with_options`).
   - CLI still delegates full runs to library pipeline.
   - FastAPI thin layer still present with required endpoints.
3. **Containerization artifacts**
   - `Dockerfile` present and installs package in image.
   - `docker-compose.yml` present with persistent volume mounts.

## Improvements made in this audit

- Updated compose service command to honor env-configurable host/port values.
- Added compose `healthcheck` against `/reports` for better startup observability.

## Readiness result

### Ready now
- Local ETL engine + tests.
- Thin API service boundary.
- Docker + Compose scaffolding with persistence and healthcheck.

### Remaining before real UI testing phase
- Add actual UI app directory (`ui/`) and service in compose (likely Node 20 + Next/SvelteKit).
- Add UI smoke tests (Playwright/Cypress) against compose stack.
- Add one-click script (`make up` / `scripts/dev_up.sh`) for local team onboarding.

## Proposed Phase-Next checklist

1. Add `ui/` app (mobile-first layout).
2. Extend compose with `finance-etl-ui` service on `${FINANCE_ETL_UI_PORT:-3000}`.
3. Add API_URL wiring from UI -> API (`http://finance-etl-api:8000`).
4. Add a minimal UI smoke suite:
   - load dashboard,
   - list runs,
   - load reports,
   - render chart JSON endpoint.
5. Add screenshot artifacts to README once UI exists.

## Notes on environment limitations from this audit

- Packaging build checks (`python -m build`) remain blocked in this environment due missing local build backend module and package-index/proxy restrictions for dependency retrieval.
