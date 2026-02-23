"""
CLI entry point for finance_etl.

Commands:
  run       — full pipeline (ingest → profile → map → normalize → validate → load → parquet → analytics)
  ingest    — register files only
  validate  — show validation report for a run
  parquet   — refresh Parquet snapshot
  analytics — export analytics CSVs
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import click

from finance_etl.db import get_connection
from finance_etl.ingest import create_run, finalize_run, register_files
from finance_etl.profile import profile_file
from finance_etl.pipeline import run_with_options
from finance_etl.parquet import refresh_parquet
from finance_etl.analytics import run_analytics
from finance_etl.utils.log import get_logger
from finance_etl.api import create_app


# ---------------------------------------------------------------------------
# Shared defaults
# ---------------------------------------------------------------------------
DEFAULT_DB = "data/db/finance.duckdb"
DEFAULT_MAPPINGS = "config/mappings"
DEFAULT_RAW = "data/raw"
DEFAULT_PROFILES = "data/profiles"
DEFAULT_VALIDATION = "data/validation"
DEFAULT_LOGS = "data/logs"
DEFAULT_REPORTS = "data/reports"
DEFAULT_MASTER = "data/master"


@click.group()
def main():
    """finance_etl — Local deterministic bank transaction ETL."""
    pass


# ---------------------------------------------------------------------------
# finance_etl run
# ---------------------------------------------------------------------------
@main.command("run")
@click.option("--inputs", "-i", multiple=True, required=True, help="CSV file paths to ingest")
@click.option("--mapping", "-m", "mapping_path", default=None,
              help="Path to a specific mapping YAML (or auto-detect by bank_key)")
@click.option("--bank-key", default=None,
              help="Bank key to auto-locate mapping YAML in --mappings-dir")
@click.option("--mappings-dir", default=DEFAULT_MAPPINGS, show_default=True)
@click.option("--account-name", default=None, help="Override account_name from mapping")
@click.option("--account-id", default=None, help="Override account_id from mapping")
@click.option("--db", "db_path", default=DEFAULT_DB, show_default=True)
@click.option("--raw-dir", default=DEFAULT_RAW, show_default=True)
@click.option("--profiles-dir", default=DEFAULT_PROFILES, show_default=True)
@click.option("--validation-dir", default=DEFAULT_VALIDATION, show_default=True)
@click.option("--logs-dir", default=DEFAULT_LOGS, show_default=True)
@click.option("--reports-dir", default=DEFAULT_REPORTS, show_default=True)
@click.option("--master-dir", default=DEFAULT_MASTER, show_default=True)
@click.option("--no-parquet", is_flag=True, default=False, help="Skip Parquet refresh")
@click.option("--no-analytics", is_flag=True, default=False, help="Skip analytics export")
@click.option("--force-parquet", is_flag=True, default=False,
              help="Force Parquet refresh even if no new rows")
def cmd_run(
    inputs, mapping_path, bank_key, mappings_dir, account_name, account_id,
    db_path, raw_dir, profiles_dir, validation_dir, logs_dir, reports_dir,
    master_dir, no_parquet, no_analytics, force_parquet,
):
    """Run the full ETL pipeline."""
    try:
        result = run_with_options(
            inputs=inputs,
            db_path=db_path,
            mappings_dir=mappings_dir,
            mapping_path=mapping_path,
            bank_key=bank_key,
            account_name=account_name,
            account_id=account_id,
            raw_dir=raw_dir,
            profiles_dir=profiles_dir,
            validation_dir=validation_dir,
            logs_dir=logs_dir,
            reports_dir=reports_dir,
            master_dir=master_dir,
            no_parquet=no_parquet,
            no_analytics=no_analytics,
            force_parquet=force_parquet,
        )
        click.echo(f"Run complete: {result.run_id}")
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# finance_etl ingest
# ---------------------------------------------------------------------------
@main.command("ingest")
@click.option("--inputs", "-i", multiple=True, required=True)
@click.option("--db", "db_path", default=DEFAULT_DB, show_default=True)
@click.option("--raw-dir", default=DEFAULT_RAW, show_default=True)
@click.option("--profiles-dir", default=DEFAULT_PROFILES, show_default=True)
def cmd_ingest(inputs, db_path, raw_dir, profiles_dir):
    """Register and profile CSV files without running the full pipeline."""
    run_id = uuid.uuid4().hex[:16]
    log = get_logger("finance_etl.ingest")
    conn = get_connection(db_path)
    csv_paths = [Path(p) for p in inputs]
    create_run(conn, run_id, len(csv_paths))
    regs = register_files(conn, csv_paths, run_id, Path(raw_dir))
    for reg in regs:
        profile_file(conn, reg["file_hash"], reg["ingested_path"], Path(profiles_dir))
    finalize_run(conn, run_id, "success",
                 {"rows_in": 0, "rows_staged": 0, "rows_normalized": 0,
                  "rows_loaded": 0, "errors_count": 0})
    log.info("Ingest complete for %d files.", len(regs))
    conn.close()


# ---------------------------------------------------------------------------
# finance_etl validate
# ---------------------------------------------------------------------------
@main.command("validate")
@click.option("--run-id", default=None, help="Show report for specific run_id")
@click.option("--validation-dir", default=DEFAULT_VALIDATION, show_default=True)
def cmd_validate(run_id, validation_dir):
    """Print validation report for a run."""
    import json, glob
    vdir = Path(validation_dir)
    if run_id:
        path = vdir / f"{run_id}.json"
        if not path.exists():
            click.echo(f"Report not found: {path}", err=True)
            sys.exit(1)
        paths = [path]
    else:
        paths = sorted(vdir.glob("*.json"))

    for p in paths:
        with open(p) as f:
            report = json.load(f)
        click.echo(f"\n--- {p.name} ---")
        click.echo(f"  run_id         : {report.get('run_id')}")
        click.echo(f"  generated_at   : {report.get('generated_at')}")
        click.echo(f"  rows_normalized: {report.get('rows_normalized')}")
        click.echo(f"  rows_valid     : {report.get('rows_valid')}")
        click.echo(f"  critical_errors: {report.get('rows_with_critical_errors')}")
        click.echo(f"  warnings       : {report.get('rows_with_warnings')}")


# ---------------------------------------------------------------------------
# finance_etl parquet
# ---------------------------------------------------------------------------
@main.command("parquet")
@click.option("--refresh", is_flag=True, default=False)
@click.option("--db", "db_path", default=DEFAULT_DB, show_default=True)
@click.option("--master-dir", default=DEFAULT_MASTER, show_default=True)
def cmd_parquet(refresh, db_path, master_dir):
    """Refresh the Parquet snapshot."""
    if not refresh:
        click.echo("Use --refresh to actually refresh Parquet.")
        return
    conn = get_connection(db_path)
    refresh_parquet(conn, Path(master_dir), force=True, rows_loaded=0)
    conn.close()


# ---------------------------------------------------------------------------
# finance_etl analytics
# ---------------------------------------------------------------------------
@main.command("analytics")
@click.option("--out", "reports_dir", default=DEFAULT_REPORTS, show_default=True)
@click.option("--master-dir", default=DEFAULT_MASTER, show_default=True)
@click.option("--db", "db_path", default=DEFAULT_DB, show_default=True)
@click.option("--top-n", default=50, show_default=True)
def cmd_analytics(reports_dir, master_dir, db_path, top_n):
    """Export analytics CSVs from the current dataset."""
    conn = get_connection(db_path)
    exported = run_analytics(conn, Path(reports_dir), Path(master_dir), top_n=top_n)
    click.echo(f"Exported {len(exported)} report(s) to {reports_dir}")
    conn.close()


# ---------------------------------------------------------------------------
# finance_etl api
# ---------------------------------------------------------------------------
@main.command("api")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True)
@click.option("--db", "db_path", default=DEFAULT_DB, show_default=True)
@click.option("--mappings-dir", default=DEFAULT_MAPPINGS, show_default=True)
@click.option("--reports-dir", default=DEFAULT_REPORTS, show_default=True)
def cmd_api(host, port, db_path, mappings_dir, reports_dir):
    """Run thin FastAPI service for runs/reports/charts."""
    try:
        import uvicorn
    except ImportError:
        click.echo("ERROR: uvicorn is required for `finance_etl api`", err=True)
        sys.exit(1)

    app = create_app(db_path=db_path, mappings_dir=mappings_dir, reports_dir=reports_dir)
    uvicorn.run(app, host=host, port=port)
