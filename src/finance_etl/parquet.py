"""
Stage 8 — Parquet export.

Refreshes the partitioned Parquet snapshot from transactions_norm.
Uses DuckDB COPY TO for fast, memory-efficient export.
"""
from __future__ import annotations

from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.utils.log import get_logger

log = get_logger(__name__)


def refresh_parquet(
    conn,
    master_dir: Path,
    partitioned: bool = True,
    force: bool = False,
    rows_loaded: int = 0,
) -> bool:
    """
    Export transactions_norm to Parquet.

    Only runs if rows_loaded > 0 or force=True (per design_rules.txt §7).
    Returns True if export was performed.
    """
    if rows_loaded == 0 and not force:
        log.info("Parquet refresh skipped (no new rows and --force not set).")
        return False

    master_dir.mkdir(parents=True, exist_ok=True)

    if partitioned:
        out_path = master_dir / "transactions_norm"
        out_path.mkdir(parents=True, exist_ok=True)
        log.info("Exporting partitioned Parquet to %s ...", out_path)
        conn.execute(f"""
            COPY (
              SELECT
                *,
                EXTRACT(year FROM transaction_date)::INTEGER  AS year,
                EXTRACT(month FROM transaction_date)::INTEGER AS month
              FROM transactions_norm
            )
            TO '{out_path}'
            (FORMAT PARQUET, PARTITION_BY (year, month), COMPRESSION ZSTD, OVERWRITE_OR_IGNORE true)
        """)
    else:
        out_path = master_dir / "transactions_norm.parquet"
        log.info("Exporting single Parquet file to %s ...", out_path)
        conn.execute(f"""
            COPY (SELECT * FROM transactions_norm)
            TO '{out_path}'
            (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

    log.info("Parquet export complete.")
    return True


def parquet_source(master_dir: Path, partitioned: bool = True) -> str:
    """Return the DuckDB read_parquet() path string for analytics queries."""
    if partitioned:
        return str(master_dir / "transactions_norm/**/*.parquet")
    return str(master_dir / "transactions_norm.parquet")
