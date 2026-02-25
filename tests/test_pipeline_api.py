from pathlib import Path
from types import SimpleNamespace

import pytest

from finance_etl.pipeline import chart_from_report_csv, run
from finance_etl.db import get_connection
from finance_etl.ingest import create_run, register_files
from finance_etl.mapping import map_and_stage
from finance_etl.normalize import normalize_staged_rows


def test_run_requires_single_mapping_yaml(tmp_path: Path):
    mappings = tmp_path / "mappings"
    mappings.mkdir()
    (mappings / "a.yaml").write_text("bank_key: a\n")
    (mappings / "b.yaml").write_text("bank_key: b\n")

    with pytest.raises(ValueError, match="Expected exactly one mapping YAML"):
        run(inputs=[], mapping_dir=mappings, db_path=tmp_path / "db.duckdb")


def test_chart_from_report_csv(tmp_path: Path):
    p = tmp_path / "r.csv"
    p.write_text("month,spend\n2024-01,10\n")
    rows = chart_from_report_csv(p)
    assert rows == [{"month": "2024-01", "spend": "10"}]


def test_run_with_options_honors_supplied_run_id(monkeypatch, tmp_path: Path):
    from finance_etl import pipeline

    class DummyConn:
        def close(self):
            pass

    monkeypatch.setattr(pipeline, "load_mapping", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline, "get_connection", lambda *_args, **_kwargs: DummyConn())

    supplied_run_id = "fixed-run-id"

    def fake_create_run(_conn, run_id, _files_count):
        assert run_id == supplied_run_id
        raise RuntimeError("stop-after-assert")

    monkeypatch.setattr(pipeline, "create_run", fake_create_run)

    with pytest.raises(RuntimeError, match="stop-after-assert"):
        pipeline.run_with_options(
            inputs=[],
            db_path=tmp_path / "db.duckdb",
            mapping_path=str(tmp_path / "mapping.yaml"),
            run_id=supplied_run_id,
        )


# ---------------------------------------------------------------------------
# Feature 2: _build_report_sql generates correct grouped SQL
# ---------------------------------------------------------------------------

def test_build_report_sql_grouped_by_category():
    """_build_report_sql with group_by=category produces valid aggregation SQL."""
    from finance_etl.api import _build_report_sql

    payload = SimpleNamespace(
        filters=[{"field": "category", "op": "not_null", "value": None}],
        group_by=["category"],
        bucket=None,
        date_from=None,
        date_to=None,
        limit=100,
    )
    sql, params, col_names = _build_report_sql(payload)

    assert "GROUP BY" in sql, "Grouped query must contain GROUP BY"
    assert "category" in sql
    assert "COUNT(*)" in sql
    assert "SUM(amount)" in sql
    assert "category" in col_names
    assert "row_count" in col_names
    assert "net_amount" in col_names
    # WHERE clause for not_null filter
    assert "IS NOT NULL" in sql
    # No params for is_null / not_null operators
    assert params == []


# ---------------------------------------------------------------------------
# Delete import: DELETE /runs/{run_id} removes run + staged + norm rows
# ---------------------------------------------------------------------------

def test_delete_run_removes_run_and_transactions(tmp_path: Path):
    """DELETE /runs/{run_id} removes the run record, staged rows, and norm rows."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Seed a run record directly into the DB
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, files_count) VALUES (?, NOW(), 'success', 0)",
        ["deltest01"],
    )
    conn.execute(
        "INSERT INTO transactions_stage (run_id, file_hash, source_file, source_row, "
        "bank_name, account_name, account_id, transaction_date_raw, posted_date_raw, "
        "description_raw, amount_raw, debit_raw, credit_raw, money_in_raw, money_out_raw, "
        "dc_flag_raw, currency_raw, extra_json) VALUES "
        "('deltest01','fhash01','f.csv',2,'B','Acc','a1','2024-01-01','','Coffee','-5','','','','','','USD','{}')",
    )
    conn.close()

    resp = client.delete("/runs/deltest01")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    conn2 = get_connection(db_path, read_only=True)
    run_rows = conn2.execute("SELECT count(*) FROM runs WHERE run_id='deltest01'").fetchone()[0]
    stage_rows = conn2.execute("SELECT count(*) FROM transactions_stage WHERE run_id='deltest01'").fetchone()[0]
    conn2.close()
    assert run_rows == 0, "Run record must be deleted"
    assert stage_rows == 0, "Staged rows must be deleted"


# ---------------------------------------------------------------------------
# Mapping persistence: category flows CSV → staged → normalized
# ---------------------------------------------------------------------------

def test_category_flows_through_pipeline(tmp_path: Path):
    """category mapped in col_map reaches transactions_norm.category (not NULL)."""
    # Write a small CSV with a Category column
    csv_path = tmp_path / "bank.csv"
    csv_path.write_text("Date,Amount,Description,Category\n2024-05-01,-12.50,Coffee,Food\n")

    mapping_dict = {
        "bank_key":             "testbank",
        "bank_name":            "Test Bank",
        "account_name":         "Checking",
        "account_id":           "chk001",
        "amount_format_family": "signed",
        "column_map": {
            "Description": "description",
            "Category":    "category",
        },
        "date":   {"transaction_date": "Date", "date_format": "%Y-%m-%d"},
        "amount": {"signed_amount": "Amount"},
        "currency_default": "USD",
    }

    db_path = tmp_path / "cat_test.duckdb"
    conn = get_connection(db_path)
    run_id = "cattest01"
    create_run(conn, run_id, 1)

    regs = register_files(conn, [csv_path], run_id, tmp_path / "raw")
    reg = regs[0]

    staged = map_and_stage(conn, reg["ingested_path"], reg["file_hash"], run_id, mapping_dict)
    assert staged == 1

    normalized, errors = normalize_staged_rows(conn, run_id, mapping_dict)
    conn.close()

    assert errors == [], f"Unexpected errors: {errors}"
    assert len(normalized) == 1
    assert normalized[0]["category"] == "Food", (
        "category must be populated from CSV; was None (pipeline bug fixed)"
    )


# ---------------------------------------------------------------------------
# Preview endpoint: merchant/category surfaced from extra_json
# ---------------------------------------------------------------------------

def test_preview_endpoint_returns_merchant_and_category(tmp_path: Path):
    """GET /runs/{run_id}/preview includes merchant/category parsed from extra_json."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "prev_test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, files_count) VALUES (?, NOW(), 'staged', 0)",
        ["prevtest01"],
    )
    import json as _json
    extra = _json.dumps({"merchant": "Starbucks", "category": "Coffee"})
    conn.execute(
        "INSERT INTO transactions_stage (run_id, file_hash, source_file, source_row, "
        "bank_name, account_name, account_id, transaction_date_raw, posted_date_raw, "
        "description_raw, amount_raw, debit_raw, credit_raw, money_in_raw, money_out_raw, "
        "dc_flag_raw, currency_raw, extra_json) VALUES "
        "(?, 'fhash02', 'f.csv', 2, 'MyBank', 'Checking', 'chk01', "
        "'2024-03-01', '', 'Starbucks coffee', '-5.50', '', '', '', '', '', 'USD', ?)",
        ["prevtest01", extra],
    )
    conn.close()

    resp = client.get("/runs/prevtest01/preview")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0].get("merchant") == "Starbucks", "merchant must be surfaced from extra_json"
    assert rows[0].get("category") == "Coffee", "category must be surfaced from extra_json"


# ---------------------------------------------------------------------------
# Custom report builder: _build_report_sql "include all" path (no filter)
# ---------------------------------------------------------------------------

def test_build_report_sql_no_filters_returns_all_rows():
    """_build_report_sql with empty filters list returns ungrouped select without WHERE."""
    from finance_etl.api import _build_report_sql

    payload = SimpleNamespace(
        filters=[],
        group_by=[],
        bucket=None,
        date_from=None,
        date_to=None,
        limit=50,
    )
    sql, params, col_names = _build_report_sql(payload)

    assert "WHERE" not in sql, "No WHERE clause expected when filters list is empty"
    assert "GROUP BY" not in sql, "No GROUP BY expected when group_by is empty"
    assert params == []
