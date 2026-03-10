# DEVELOPMENT

Developer workflow for `finance_etl`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## Run tests

```bash
pytest -q
```

or verbose:

```bash
pytest tests/ -v
```

## Linting

No linter is enforced in this repository yet.
Recommended next step:
- add `ruff` + `mypy` and wire into CI.

## Build package

```bash
python -m build
```

If `build` is missing:

```bash
pip install build
python -m build
```

## Run CLI locally

```bash
finance_etl --help
finance_etl run --help
```

## Run API locally

```bash
finance_etl api --host 0.0.0.0 --port 8000
```

## Key invariants to preserve while changing code

- Outflow is negative; inflow is positive.
- Money parsing/loading must avoid float drift.
- Date ambiguity must fail fast.
- Re-runs must stay idempotent.

## Suggested contribution checklist

1. Add/adjust tests for behavior changes.
2. Run full `pytest -q`.
3. Update docs (`README`, `docs/CONFIG.md`, etc.) when behavior changes.
4. Keep CLI thin; put orchestration in library modules.
