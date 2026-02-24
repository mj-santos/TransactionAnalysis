"""Stable programmatic pipeline API (library-first, CLI reuses this)."""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from finance_etl.analytics import run_analytics
from finance_etl.db import get_connection
from finance_etl.ingest import create_run, finalize_run, register_files
from finance_etl.load import load_normalized
from finance_etl.mapping import find_mapping, load_mapping, map_and_stage
from finance_etl.normalize import normalize_staged_rows
from finance_etl.parquet import refresh_parquet
from finance_etl.profile import profile_file
from finance_etl.utils.log import get_logger
from finance_etl.validate import validate_normalized


@dataclass(frozen=True)
class RunResult:
    run_id: str
    counts: dict[str, int]


# ---------------------------------------------------------------------------
# In-memory store for staged (preview) runs awaiting commit
# Key: run_id, Value: state dict with mapping, paths, and counts
# ---------------------------------------------------------------------------
_staged_runs: dict[str, dict] = {}


def run(
    inputs: list[str | Path],
    mapping_dir: str | Path,
    db_path: str | Path,
) -> str:
    """Stable API required for integrations: run(inputs, mapping_dir, db_path) -> run_id.

    Expects exactly one YAML in mapping_dir. For multi-bank directories, use run_with_options().
    """
    mapping_candidates = sorted(Path(mapping_dir).glob("*.yaml"))
    if len(mapping_candidates) != 1:
        raise ValueError(
            f"Expected exactly one mapping YAML in {mapping_dir}, found {len(mapping_candidates)}. "
            "Use run_with_options(..., mapping_path=...) or bank_key=... for multi-bank dirs."
        )

    result = run_with_options(
        inputs=inputs,
        db_path=db_path,
        mappings_dir=mapping_dir,
        mapping_path=str(mapping_candidates[0]),
    )
    return result.run_id


def run_with_options(
    inputs,
    db_path,
    mappings_dir="config/mappings",
    mapping_path=None,
    bank_key=None,
    account_name=None,
    account_id=None,
    raw_dir="data/raw",
    profiles_dir="data/profiles",
    validation_dir="data/validation",
    logs_dir="data/logs",
    reports_dir="data/reports",
    master_dir="data/master",
    no_parquet=False,
    no_analytics=False,
    force_parquet=False,
    preview_only=False,
    run_id=None,
) -> RunResult:
    """Full-featured programmatic run API used by CLI and web API.

    When preview_only=True the pipeline runs through validate but stops before
    loading to transactions_norm.  Call commit_run(run_id) to finish the load.
    """
    run_id = run_id or uuid.uuid4().hex[:16]
    log = get_logger("finance_etl.run", Path(logs_dir), run_id)
    log.info("=== finance_etl run %s (preview_only=%s) ===", run_id, preview_only)

    csv_paths = [Path(p) for p in inputs]

    if mapping_path:
        mapping = load_mapping(mapping_path)
    elif bank_key:
        mp = find_mapping(mappings_dir, bank_key)
        mapping = load_mapping(mp)
    else:
        raise ValueError("Provide mapping_path or bank_key")

    conn = get_connection(db_path)
    counts = dict(rows_in=0, rows_staged=0, rows_normalized=0, rows_loaded=0, errors_count=0)
    stage_timings: dict[str, float] = {}

    try:
        t0 = time.perf_counter()
        create_run(conn, run_id, len(csv_paths))
        registrations = register_files(conn, csv_paths, run_id, Path(raw_dir))
        stage_timings["ingest_register_s"] = time.perf_counter() - t0

        for reg in registrations:
            fhash = reg["file_hash"]
            ipath = reg["ingested_path"]

            t0 = time.perf_counter()
            profile_file(conn, fhash, ipath, Path(profiles_dir))
            stage_timings["profile_s"] = stage_timings.get("profile_s", 0.0) + (time.perf_counter() - t0)

            enc = conn.execute(
                "SELECT encoding FROM raw_files WHERE file_hash=?", [fhash]
            ).fetchone()
            enc = enc[0] if enc and enc[0] else "utf-8"
            with open(ipath, encoding=enc, errors="replace") as f:
                rows_in = sum(1 for _ in f) - 1
            counts["rows_in"] += max(rows_in, 0)

            t0 = time.perf_counter()
            staged = map_and_stage(
                conn,
                ipath,
                fhash,
                run_id,
                mapping,
                account_name_override=account_name,
                account_id_override=account_id,
            )
            counts["rows_staged"] += staged
            stage_timings["map_stage_s"] = stage_timings.get("map_stage_s", 0.0) + (time.perf_counter() - t0)

        t0 = time.perf_counter()
        normalized, norm_errors = normalize_staged_rows(conn, run_id, mapping)
        stage_timings["normalize_s"] = time.perf_counter() - t0
        counts["rows_normalized"] = len(normalized)
        counts["errors_count"] += len(norm_errors)

        t0 = time.perf_counter()
        valid_rows, report = validate_normalized(normalized, norm_errors, run_id, Path(validation_dir))
        stage_timings["validate_s"] = time.perf_counter() - t0
        counts["errors_count"] = report["rows_with_critical_errors"]

        if report["rows_with_critical_errors"] > 0:
            finalize_run(
                conn,
                run_id,
                "fail",
                counts,
                notes=f"{report['rows_with_critical_errors']} critical errors",
            )
            raise RuntimeError(f"Run failed validation with {report['rows_with_critical_errors']} critical errors")

        # ------------------------------------------------------------------
        # Preview gate: stop here, store state, wait for commit_run()
        # ------------------------------------------------------------------
        if preview_only:
            _staged_runs[run_id] = {
                "mapping": mapping,
                "db_path": str(db_path),
                "reports_dir": str(reports_dir),
                "master_dir": str(master_dir),
                "validation_dir": str(validation_dir),
                "logs_dir": str(logs_dir),
                "counts": dict(counts),
                "no_parquet": no_parquet,
                "no_analytics": no_analytics,
                "force_parquet": force_parquet,
            }
            finalize_run(conn, run_id, "staged", counts, notes="awaiting commit")
            conn.close()
            log.info("Run %s staged — awaiting commit.", run_id)
            return RunResult(run_id=run_id, counts=counts)

        # ------------------------------------------------------------------
        # Full commit path
        # ------------------------------------------------------------------
        t0 = time.perf_counter()
        load_result = load_normalized(conn, valid_rows)
        stage_timings["load_s"] = time.perf_counter() - t0
        counts["rows_loaded"] = load_result["rows_loaded"]

        if not no_parquet:
            t0 = time.perf_counter()
            refresh_parquet(conn, Path(master_dir), rows_loaded=counts["rows_loaded"], force=force_parquet)
            stage_timings["parquet_s"] = time.perf_counter() - t0

        if not no_analytics:
            t0 = time.perf_counter()
            run_analytics(conn, Path(reports_dir), Path(master_dir))
            stage_timings["analytics_s"] = time.perf_counter() - t0

        notes = json.dumps(
            {"stage_timings_s": {k: round(v, 6) for k, v in stage_timings.items()}},
            sort_keys=True,
        )
        finalize_run(conn, run_id, "success", counts, notes=notes)
        return RunResult(run_id=run_id, counts=counts)

    except Exception as e:
        log.exception("Pipeline failed: %s", e)
        try:
            finalize_run(conn, run_id, "fail", counts, notes=str(e))
        except Exception:
            pass
        raise
    finally:
        conn.close()


def commit_run(run_id: str) -> RunResult:
    """Load a previously staged (preview) run to the ledger and run analytics.

    Raises KeyError if the run was never staged or was already committed.
    """
    if run_id not in _staged_runs:
        raise KeyError(
            f"Run {run_id!r} is not in staged state. "
            "It was either never run in preview_only mode, already committed, or the server restarted."
        )

    state = _staged_runs.pop(run_id)
    log = get_logger("finance_etl.commit", Path(state["logs_dir"]), run_id)
    log.info("Committing staged run %s", run_id)

    conn = get_connection(state["db_path"])
    counts = dict(state["counts"])

    try:
        # Re-normalize from transactions_stage (already staged, deterministic)
        normalized, norm_errors = normalize_staged_rows(conn, run_id, state["mapping"])
        valid_rows, report = validate_normalized(
            normalized, norm_errors, run_id, Path(state["validation_dir"])
        )

        load_result = load_normalized(conn, valid_rows)
        counts["rows_loaded"] = load_result["rows_loaded"]

        if not state.get("no_parquet"):
            refresh_parquet(
                conn,
                Path(state["master_dir"]),
                rows_loaded=counts["rows_loaded"],
                force=state.get("force_parquet", False),
            )

        if not state.get("no_analytics"):
            run_analytics(conn, Path(state["reports_dir"]), Path(state["master_dir"]))

        finalize_run(conn, run_id, "success", counts, notes="committed from preview")
        log.info("Run %s committed successfully. rows_loaded=%d", run_id, counts["rows_loaded"])
        return RunResult(run_id=run_id, counts=counts)

    except Exception as e:
        log.exception("Commit failed for run %s: %s", run_id, e)
        try:
            finalize_run(conn, run_id, "fail", counts, notes=str(e))
        except Exception:
            pass
        raise
    finally:
        conn.close()


def get_run_status(db_path: str | Path, run_id: str) -> dict:
    """Read one run row for API/UI usage."""
    conn = get_connection(db_path, read_only=True)
    try:
        row = conn.execute(
            """
            SELECT run_id, started_at, finished_at, status, files_count,
                   rows_in, rows_staged, rows_normalized, rows_loaded, errors_count, notes
            FROM runs WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()
        if not row:
            raise KeyError(run_id)
        keys = [
            "run_id",
            "started_at",
            "finished_at",
            "status",
            "files_count",
            "rows_in",
            "rows_staged",
            "rows_normalized",
            "rows_loaded",
            "errors_count",
            "notes",
        ]
        out = dict(zip(keys, row))
        if out.get("notes"):
            try:
                out["notes"] = json.loads(out["notes"])
            except Exception:
                pass
        # Serialize datetime objects to ISO strings for JSON / Pydantic str fields
        for dt_key in ("started_at", "finished_at"):
            v = out.get(dt_key)
            if v is not None and hasattr(v, "isoformat"):
                out[dt_key] = v.isoformat()
        # Surface whether this run is currently staged in memory
        out["staged"] = run_id in _staged_runs
        return out
    finally:
        conn.close()


def chart_from_report_csv(path: Path) -> list[dict[str, str]]:
    """Convert report CSV file into JSON rows for lightweight charts."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
