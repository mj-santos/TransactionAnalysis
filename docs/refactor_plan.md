# Refactor Review: package structure, side-effects, and guardrails

## Package/entrypoint sanity
- The project is a proper `src/` package with CLI entrypoint (`finance_etl = finance_etl.cli:main`).
- CLI command graph is clean and stage-oriented.

## What belongs where
- `src/finance_etl/`: deterministic business logic and stage orchestration.
- `config/`: static user-editable schemas, mappings, category rules.
- `docs/`: architecture, runbooks, conventions, extension guides.
- `scripts/` (recommended add): ad-hoc operational scripts (backfills, data repair utilities), never imported by runtime package.

## Side-effects inventory
- File writes: ingest copy (`data/raw`), profile JSON (`data/profiles`), validation JSON (`data/validation`), reports/parquet.
- DB writes: run ledger, file registration, stage rows, normalized rows.

## What should be better
- Keep side-effects in thin wrappers and push pure transformations into helper functions.
- Persist mapping fingerprint + package version in run ledger for reproducibility.
- Add explicit schema validation for CSV headers and mapping YAML before any DB writes.

## Top-10 highest-impact / low-risk improvements
1. Persist mapping file SHA-256 and package version per run.
2. Add typed models for mapping config and run metadata.
3. Enforce unique ingested filenames per file hash (collision-safe).
4. Add run ledger guardrails (status enum, finalize target must exist).
5. Add golden fixtures for each amount family.
6. Add deterministic sorting before analytics exports where practical.
7. Add a dedicated `errors` table for queryable failures.
8. Split CLI orchestration from pure stage planner/runner.
9. Add mapping schema lint command (`finance_etl lint-mapping`).
10. Add integration test for 10x rerun idempotency.

## Functions that should be pure
- row normalization (`_normalize_row`) and amount/date parsing (already mostly pure).
- stage row building (`_build_stage_row`) should remain side-effect free.
- add pure `plan_run(...)` that returns selected stages/options without touching filesystem/DB.

## Typed models to prevent drift
- Mapping YAML (`MappingConfig`, `DateConfig`, `AmountConfig`) [implemented].
- Run ledger note payload (`RunNotes` dataclass) for stable machine-readable notes.
- Validation report object model to lock output contract.

## Guardrail insertion points
- mapping load: typed parse + family constraints.
- ingest: collision-safe file naming and duplicate run-id checks.
- finalize run: status validation and affected-row assertion.
- pre-run check: ensure all inputs exist and no duplicate input hashes in same invocation.
