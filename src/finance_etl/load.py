"""
Stage 7 — Load (dedupe).

Inserts valid normalized rows into transactions_norm.
Uses INSERT OR IGNORE pattern against the UNIQUE(transaction_fingerprint) index.
Returns counts of inserted vs skipped rows.
"""
from __future__ import annotations

from decimal import Decimal

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.utils.log import get_logger

log = get_logger(__name__)


def load_normalized(
    conn,
    valid_rows: list[dict],
    run_id: str | None = None,
) -> dict[str, int]:
    """
    Insert rows into transactions_norm, skipping duplicates.

    run_id: propagated onto every row for the Import Source dropdown
            (GET /transactions/sources groups by run_id).
    Returns {"rows_loaded": int, "dupes_skipped": int}
    """
    rows_loaded = 0
    dupes_skipped = 0

    for row in valid_rows:
        try:
            fp = row.get("transaction_fingerprint", "")
            # Check for duplicate before inserting (DuckDB has no changes() function)
            already_exists = conn.execute(
                "SELECT 1 FROM transactions_norm WHERE transaction_fingerprint = ?",
                [fp],
            ).fetchone()
            if already_exists:
                dupes_skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO transactions_norm (
                  transaction_date, posted_date, description, merchant, category,
                  amount, currency, bank_name, account_name, account_id,
                  source_file, source_row, file_hash, transaction_fingerprint,
                  statement_type, run_id,
                  transaction_subtype, resolved_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["transaction_date"],
                    row.get("posted_date"),
                    row["description"],
                    row.get("merchant"),
                    row.get("category"),
                    str(row["amount"]),
                    row.get("currency", "USD"),
                    row["bank_name"],
                    row["account_name"],
                    row["account_id"],
                    row["source_file"],
                    row["source_row"],
                    row["file_hash"],
                    fp,
                    # Feature 1: 'bank' or 'credit_card' — never mix in aggregations
                    row.get("statement_type"),
                    # Source tracking: links row back to originating run
                    run_id,
                    # CC subtype model: 'spending' | 'payment' | 'adjustment' | None
                    row.get("transaction_subtype"),
                    str(row["resolved_amount"]) if row.get("resolved_amount") is not None else None,
                ],
            )
            rows_loaded += 1
        except Exception as e:
            log.warning("Load error on row (fingerprint=%s): %s",
                        row.get("transaction_fingerprint", "?")[:12], e)
            dupes_skipped += 1

    log.info("Loaded %d rows, skipped %d duplicates", rows_loaded, dupes_skipped)
    return {"rows_loaded": rows_loaded, "dupes_skipped": dupes_skipped}
