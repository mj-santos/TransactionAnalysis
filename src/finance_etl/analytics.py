"""
Stage 9 — Analytics exports.

Runs the SQL analytics pack from database_design.txt and writes CSV reports.
Reads from partitioned Parquet when available, falls back to transactions_norm.
"""
from __future__ import annotations

from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.parquet import parquet_source
from finance_etl.utils.log import get_logger

log = get_logger(__name__)


def run_analytics(
    conn,
    reports_dir: Path,
    master_dir: Path,
    top_n: int = 50,
    partitioned: bool = True,
) -> list[Path]:
    """
    Run all analytics queries and export CSV files to reports_dir.

    Returns list of exported file paths.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    parquet_glob = parquet_source(master_dir, partitioned)

    # Determine data source
    source = _resolve_source(conn, parquet_glob)
    log.info("Analytics reading from: %s", source)

    queries = _build_queries(source, top_n)
    exported = []

    for name, sql in queries.items():
        out_path = reports_dir / f"{name}.csv"
        try:
            conn.execute(
                f"COPY ({sql}) TO '{out_path}' (HEADER, DELIMITER ',')"
            )
            exported.append(out_path)
            log.info("Exported: %s", out_path)
        except Exception as e:
            log.error("Failed to export %s: %s", name, e)

    return exported


def _resolve_source(conn, parquet_glob: str) -> str:
    """Use Parquet if available, otherwise fall back to DuckDB table."""
    try:
        conn.execute(f"SELECT 1 FROM read_parquet('{parquet_glob}') LIMIT 1")
        return f"read_parquet('{parquet_glob}')"
    except Exception:
        log.info("Parquet not found, falling back to transactions_norm table.")
        return "transactions_norm"


def _build_queries(source: str, top_n: int) -> dict[str, str]:
    return {
        "spend_by_month_category": f"""
            SELECT
              date_trunc('month', transaction_date) AS month,
              COALESCE(category, 'Uncategorized') AS category,
              SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS spend
            FROM {source}
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
        "cashflow_by_month": f"""
            SELECT
              date_trunc('month', transaction_date) AS month,
              SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END)  AS inflow,
              SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS outflow,
              SUM(amount) AS net
            FROM {source}
            GROUP BY 1
            ORDER BY 1
        """,
        "spend_by_merchant": f"""
            SELECT
              COALESCE(merchant, description) AS merchant,
              SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS spend
            FROM {source}
            GROUP BY 1
            ORDER BY 2 DESC
        """,
        "totals_by_account": f"""
            SELECT
              bank_name,
              account_name,
              account_id,
              SUM(amount) AS net
            FROM {source}
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        """,
        "top_merchants": f"""
            SELECT
              COALESCE(merchant, description) AS merchant,
              SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS spend
            FROM {source}
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT {top_n}
        """,
    }
