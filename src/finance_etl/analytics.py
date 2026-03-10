"""
Stage 9 — Analytics exports.

Runs the SQL analytics pack from database_design.txt and writes CSV reports.
Reads from partitioned Parquet when available, falls back to transactions_norm.
"""
from __future__ import annotations

from pathlib import Path

from finance_etl.utils.query_helpers import INCOME_FILTER

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
    statement_type: str | None = None,
) -> list[Path]:
    """
    Run all analytics queries and export CSV files to reports_dir.

    Returns list of exported file paths.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    parquet_glob = parquet_source(master_dir, partitioned)

    # Determine data source
    source = _resolve_source(conn, parquet_glob)
    log.info("Analytics reading from: %s (statement_type=%s)", source, statement_type)

    queries = _build_queries(source, top_n, statement_type)
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


def _build_queries(source: str, top_n: int, statement_type: str | None = None) -> dict[str, str]:
    # Feature 1: scope reports by statement_type when provided.
    # Credit-card aggregations must NEVER include bank rows; bank must NEVER include credit-card.
    if statement_type:
        st_filter = f" WHERE statement_type = '{statement_type}'"
        st_and    = f" AND statement_type = '{statement_type}'"
    else:
        st_filter = ""
        st_and    = ""

    # Feature 3: new aggregate definitions (old sign-filtered versions removed)
    # total_spend  = SUM of ALL resolved_amount values (gross signed sum, no sign filtering)
    # INCOME_FILTER — see query_helpers.py
    # net_amount   = total_income − |outflows| = income minus absolute outflow
    _null_safe = "COALESCE(amount, 0)"

    return {
        "spend_by_month_category": f"""
            SELECT
              date_trunc('month', transaction_date) AS month,
              COALESCE(category, 'Uncategorized')   AS category,
              -- Feature 3: total_spend = gross signed sum (all amounts, no sign filter)
              SUM({_null_safe}) AS total_spend
            FROM {source}{st_filter}
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
        "cashflow_by_month": f"""
            SELECT
              date_trunc('month', transaction_date) AS month,
              -- INCOME_FILTER — see query_helpers.py
              SUM(CASE WHEN {INCOME_FILTER}
                       THEN {_null_safe} ELSE 0 END) AS total_income,
              -- total_outflow = absolute value of outflows
              ABS(SUM(CASE WHEN {_null_safe} < 0 THEN {_null_safe} ELSE 0 END)) AS total_outflow,
              -- net_amount = total_income - |outflows|
              SUM(CASE WHEN {INCOME_FILTER}
                       THEN {_null_safe} ELSE 0 END)
                - ABS(SUM(CASE WHEN {_null_safe} < 0 THEN {_null_safe} ELSE 0 END)) AS net_amount
            FROM {source}{st_filter}
            GROUP BY 1
            ORDER BY 1
        """,
        "spend_by_merchant": f"""
            SELECT
              COALESCE(merchant, description) AS merchant,
              -- Feature 3: gross signed sum scoped to statement_type
              SUM({_null_safe}) AS total_spend
            FROM {source}{st_filter}
            GROUP BY 1
            ORDER BY 2
        """,
        "totals_by_account": f"""
            SELECT
              bank_name,
              account_name,
              account_id,
              statement_type,
              -- Feature 3 / Feature 1: net per account, already scoped above
              SUM({_null_safe}) AS net_amount
            FROM {source}{st_filter}
            GROUP BY 1, 2, 3, 4
            ORDER BY 1, 2, 3
        """,
        "top_merchants": f"""
            SELECT
              COALESCE(merchant, description) AS merchant,
              SUM({_null_safe}) AS total_spend
            FROM {source}{st_filter}
            GROUP BY 1
            ORDER BY ABS(SUM({_null_safe})) DESC
            LIMIT {top_n}
        """,
    }
