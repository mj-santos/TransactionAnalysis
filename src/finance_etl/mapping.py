"""
Stage 4 — Mapping (config-driven).

Loads a bank mapping YAML, reads the CSV, and produces stage rows
that are inserted into transactions_stage.

No bank-specific column names live here — everything comes from YAML.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from finance_etl.models import parse_mapping_config
from finance_etl.utils.log import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_mapping(mapping_path: str | Path) -> dict[str, Any]:
    """Load and validate a bank mapping YAML, returning plain dict for compatibility."""
    with open(mapping_path) as f:
        cfg = yaml.safe_load(f) or {}

    # typed validation guardrail; raises ValueError with actionable messages
    parse_mapping_config(cfg, str(mapping_path))
    return cfg


def find_mapping(mappings_dir: str | Path, bank_key: str) -> Path:
    """Find a YAML file matching bank_key in mappings_dir."""
    for p in Path(mappings_dir).glob("*.yaml"):
        try:
            cfg = load_mapping(p)
            if cfg.get("bank_key") == bank_key:
                return p
        except Exception:
            continue
    raise FileNotFoundError(
        f"No mapping found for bank_key={bank_key!r} in {mappings_dir}"
    )




# ---------------------------------------------------------------------------
# CSV reader + mapper
# ---------------------------------------------------------------------------

def map_and_stage(
    conn,
    ingested_path: str,
    file_hash: str,
    run_id: str,
    mapping: dict[str, Any],
    account_name_override: str | None = None,
    account_id_override: str | None = None,
) -> int:
    """
    Read CSV, apply mapping, insert rows into transactions_stage.

    Returns the number of rows staged.
    """
    enc = _get_encoding(conn, file_hash)
    delim = _get_delimiter(conn, file_hash)
    bank_name = mapping["bank_name"]
    account_name = account_name_override or mapping.get("account_name", "")
    account_id = account_id_override or mapping.get("account_id", "")
    col_map: dict[str, str] = mapping.get("column_map", {})
    text_cols: dict[str, str] = mapping.get("text_cols", {})   # canonical→csv (many-to-one safe)
    drop_cols: list[str] = mapping.get("drop_columns", [])
    category_override: str | None = mapping.get("category_override") or None
    date_cfg: dict = mapping.get("date", {})
    amount_cfg: dict = mapping.get("amount", {})
    family: str = mapping["amount_format_family"]
    currency_default: str = mapping.get("currency_default", "USD")

    rows_staged = 0

    with open(ingested_path, encoding=enc, errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no headers: {ingested_path}")

        headers = [h.strip() for h in reader.fieldnames]
        _validate_required_cols(headers, date_cfg, amount_cfg, family, col_map)

        for row_idx, raw_row in enumerate(reader, start=2):
            # Normalize header whitespace
            row = {k.strip(): v for k, v in raw_row.items() if k is not None}

            # Drop columns
            for col in drop_cols:
                row.pop(col, None)

            # Build stage row
            stage = _build_stage_row(
                row=row,
                row_idx=row_idx,
                run_id=run_id,
                file_hash=file_hash,
                source_file=ingested_path,
                bank_name=bank_name,
                account_name=account_name,
                account_id=account_id,
                col_map=col_map,
                text_cols=text_cols,
                date_cfg=date_cfg,
                amount_cfg=amount_cfg,
                family=family,
                currency_default=currency_default,
                category_override=category_override,
            )

            _insert_stage_row(conn, stage)
            rows_staged += 1

    log.info("Staged %d rows for %s", rows_staged, file_hash[:12])
    return rows_staged


def _get_encoding(conn, file_hash: str) -> str:
    row = conn.execute(
        "SELECT encoding FROM raw_files WHERE file_hash = ?", [file_hash]
    ).fetchone()
    return (row[0] if row and row[0] else "utf-8")


def _get_delimiter(conn, file_hash: str) -> str:
    row = conn.execute(
        "SELECT delimiter FROM raw_files WHERE file_hash = ?", [file_hash]
    ).fetchone()
    return (row[0] if row and row[0] else ",")


def _validate_required_cols(
    headers: list[str],
    date_cfg: dict,
    amount_cfg: dict,
    family: str,
    col_map: dict,
) -> None:
    missing = []
    # Date columns
    tx_date_col = date_cfg.get("transaction_date")
    if tx_date_col and tx_date_col not in headers:
        missing.append(tx_date_col)
    # Amount columns by family
    if family == "signed":
        col = amount_cfg.get("signed_amount")
        if col and col not in headers:
            missing.append(col)
    elif family == "debit_credit":
        for key in ("debit_col", "credit_col"):
            col = amount_cfg.get(key)
            if col and col not in headers:
                missing.append(col)
    elif family == "money_in_out":
        for key in ("money_in_col", "money_out_col"):
            col = amount_cfg.get(key)
            if col and col not in headers:
                missing.append(col)
    elif family == "amount_plus_flag":
        for key in ("amount_col", "dc_flag_col"):
            col = amount_cfg.get(key)
            if col and col not in headers:
                missing.append(col)
    if missing:
        raise ValueError(f"Required columns missing from CSV: {missing}")


def _build_stage_row(
    row: dict,
    row_idx: int,
    run_id: str,
    file_hash: str,
    source_file: str,
    bank_name: str,
    account_name: str,
    account_id: str,
    col_map: dict,
    date_cfg: dict,
    amount_cfg: dict,
    family: str,
    currency_default: str,
    text_cols: dict | None = None,
    category_override: str | None = None,
) -> dict:
    def get(col: str | None) -> str:
        if not col:
            return ""
        return (row.get(col) or "").strip()

    # Build canonical→source lookup.
    # Prefer text_cols (supports many-to-one: description AND merchant sharing one CSV col).
    # Fall back to reversing col_map for mappings not in text_cols.
    _reversed_col_map = {canon: src for src, canon in col_map.items()}
    canon_to_source = {**_reversed_col_map, **(text_cols or {})}

    description_col = canon_to_source.get("description", "description")
    description_raw = get(description_col)

    # Extra: collect unmapped non-canonical columns
    canonical_cols = {
        date_cfg.get("transaction_date"), date_cfg.get("posted_date"),
        amount_cfg.get("signed_amount"), amount_cfg.get("debit_col"),
        amount_cfg.get("credit_col"), amount_cfg.get("money_in_col"),
        amount_cfg.get("money_out_col"), amount_cfg.get("amount_col"),
        amount_cfg.get("dc_flag_col"),
    } | set(col_map.keys())
    extra = {k: v for k, v in row.items() if k not in canonical_cols and v}

    # Carry merchant, category, and notes through extra_json with canonical keys
    # so normalize.py can populate transactions_norm.merchant / .category.
    for _canon in ("merchant", "category", "notes"):
        _src = canon_to_source.get(_canon)
        if _src:
            _val = get(_src)
            if _val:
                extra[_canon] = _val

    # category_override (letters A–Z only) takes precedence over the CSV column.
    if category_override:
        extra["category"] = category_override

    return {
        "run_id": run_id,
        "file_hash": file_hash,
        "source_file": source_file,
        "source_row": row_idx,
        "bank_name": bank_name,
        "account_name": account_name,
        "account_id": account_id,
        "transaction_date_raw": get(date_cfg.get("transaction_date")),
        "posted_date_raw": get(date_cfg.get("posted_date")),
        "description_raw": description_raw,
        "amount_raw": get(amount_cfg.get("signed_amount")) if family == "signed" else
                      get(amount_cfg.get("amount_col")) if family == "amount_plus_flag" else "",
        "debit_raw": get(amount_cfg.get("debit_col")) if family == "debit_credit" else "",
        "credit_raw": get(amount_cfg.get("credit_col")) if family == "debit_credit" else "",
        "money_in_raw": get(amount_cfg.get("money_in_col")) if family == "money_in_out" else "",
        "money_out_raw": get(amount_cfg.get("money_out_col")) if family == "money_in_out" else "",
        "dc_flag_raw": get(amount_cfg.get("dc_flag_col")) if family == "amount_plus_flag" else "",
        "currency_raw": get(canon_to_source.get("currency")) or currency_default,
        "extra_json": json.dumps(extra) if extra else "{}",
        # Feature 2: optional fallback debit/credit columns alongside any family
        "amount_debit_raw": get(amount_cfg.get("amount_debit")),
        "amount_credit_raw": get(amount_cfg.get("amount_credit")),
    }


def _insert_stage_row(conn, s: dict) -> None:
    conn.execute(
        """
        INSERT INTO transactions_stage (
          run_id, file_hash, source_file, source_row,
          bank_name, account_name, account_id,
          transaction_date_raw, posted_date_raw, description_raw,
          amount_raw, debit_raw, credit_raw,
          money_in_raw, money_out_raw, dc_flag_raw,
          currency_raw, extra_json,
          amount_debit_raw, amount_credit_raw
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            s["run_id"], s["file_hash"], s["source_file"], s["source_row"],
            s["bank_name"], s["account_name"], s["account_id"],
            s["transaction_date_raw"], s["posted_date_raw"], s["description_raw"],
            s["amount_raw"], s["debit_raw"], s["credit_raw"],
            s["money_in_raw"], s["money_out_raw"], s["dc_flag_raw"],
            s["currency_raw"], s["extra_json"],
            # Feature 2: new canonical debit/credit columns (auditable)
            s["amount_debit_raw"], s["amount_credit_raw"],
        ],
    )
