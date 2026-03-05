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

    def fake_create_run(_conn, run_id, _files_count, statement_type=None, run_label=None):
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
    # Feature 3: aggregate expressions now use COALESCE(amount, 0) for null safety
    assert "COALESCE(amount, 0)" in sql
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


# ---------------------------------------------------------------------------
# Feature 2: resolve_amount priority chain
# ---------------------------------------------------------------------------

def test_resolve_amount_signed_preferred():
    """Step 1: signed amount_raw is used when populated, ignoring debit/credit fallback."""
    from decimal import Decimal
    from finance_etl.normalize import resolve_amount

    row = {
        "amount_raw":        "-42.50",
        "amount_debit_raw":  "100.00",  # must be ignored — Step 1 wins
        "amount_credit_raw": "",
    }
    assert resolve_amount(row, "signed", {}, {}) == Decimal("-42.50")


def test_resolve_amount_fallback_to_debit_credit():
    """Step 2: falls back to amount_debit_raw / amount_credit_raw when family field is empty."""
    from decimal import Decimal
    from finance_etl.normalize import resolve_amount

    row = {
        "amount_raw":        "",         # signed family but empty → no Step 1 match
        "amount_debit_raw":  "30.00",    # outflow
        "amount_credit_raw": "10.00",    # inflow
        "source_row":        2,
        "source_file":       "test.csv",
    }
    # Formula: credit − debit = 10 − 30 = −20 (net outflow, negative)
    assert resolve_amount(row, "signed", {}, {}) == Decimal("-20.00")


def test_resolve_amount_credit_only():
    """Step 2: credit_raw alone resolves to a positive inflow (debit treated as 0)."""
    from decimal import Decimal
    from finance_etl.normalize import resolve_amount

    row = {
        "amount_raw":        "",
        "amount_debit_raw":  "",
        "amount_credit_raw": "500.00",
        "source_row":        3,
    }
    assert resolve_amount(row, "signed", {}, {}) == Decimal("500.00")  # 500 − 0


def test_resolve_amount_all_empty_raises():
    """Step 3: NormalizationError raised when every amount field is empty."""
    from finance_etl.normalize import resolve_amount, NormalizationError

    row = {
        "amount_raw":        "",
        "debit_raw":         "",
        "credit_raw":        "",
        "money_in_raw":      "",
        "money_out_raw":     "",
        "amount_debit_raw":  "",
        "amount_credit_raw": "",
        "source_row":        5,
        "source_file":       "empty.csv",
    }
    with pytest.raises(NormalizationError, match="No amount data"):
        resolve_amount(row, "signed", {}, {})


# ---------------------------------------------------------------------------
# Feature 1: statement_type isolation — credit_card ≠ bank, never mixed
# ---------------------------------------------------------------------------

def test_statement_type_isolation(tmp_path: Path):
    """GET /transactions?type=bank returns only bank rows; credit_card query returns only CC rows."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "isolation_test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    # One bank row, one credit_card row
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_date, description, amount, currency, bank_name, account_name, "
        " account_id, source_file, source_row, file_hash, transaction_fingerprint, statement_type) "
        "VALUES "
        "(DATE '2024-01-01','Salary',1000.0,'USD','MyBank','Checking','chk01','f.csv',1,'h01','fp01','bank'),"
        "(DATE '2024-01-02','CC charge',-45.0,'USD','Visa','CC','cc01','f.csv',2,'h02','fp02','credit_card')"
    )
    conn.close()

    # bank type must never include credit_card rows
    r_bank = client.get("/transactions?type=bank")
    assert r_bank.status_code == 200
    bank_rows = r_bank.json()["rows"]
    assert len(bank_rows) == 1
    assert all(r.get("statement_type") == "bank" for r in bank_rows), \
        "Bank query must never include credit_card rows (Feature 1)"

    # credit_card type must never include bank rows
    r_cc = client.get("/transactions?type=credit_card")
    assert r_cc.status_code == 200
    cc_rows = r_cc.json()["rows"]
    assert len(cc_rows) == 1
    assert all(r.get("statement_type") == "credit_card" for r in cc_rows), \
        "Credit card query must never include bank rows (Feature 1)"


# ---------------------------------------------------------------------------
# Feature 3 + Feature 4: /transactions/totals returns correct aggregates
# ---------------------------------------------------------------------------

def test_transaction_totals_endpoint(tmp_path: Path):
    """GET /transactions/totals returns Feature 3 aggregate definitions scoped by type."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "totals_test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_date, description, amount, currency, bank_name, account_name, "
        " account_id, source_file, source_row, file_hash, transaction_fingerprint, statement_type) "
        "VALUES "
        "(DATE '2024-01-01','Salary',1000.0,'USD','Bank','Checking','chk01','f.csv',1,'h1','fp1','bank'),"
        "(DATE '2024-01-02','Rent',-500.0,'USD','Bank','Checking','chk01','f.csv',2,'h2','fp2','bank'),"
        "(DATE '2024-01-03','CC charge',-200.0,'USD','Visa','CC','cc01','f.csv',3,'h3','fp3','credit_card')"
    )
    conn.close()

    resp = client.get("/transactions/totals?type=bank")
    assert resp.status_code == 200
    t = resp.json()

    assert t["row_count"] == 2
    # Feature 3: total_income = sum of inflows (positives only)
    assert t["total_income"]  == pytest.approx(1000.0)
    # Feature 3: total_outflow = abs(sum of negatives)
    assert t["total_outflow"] == pytest.approx(500.0)
    # Feature 3: net_amount = total_income − total_outflow
    assert t["net_amount"]    == pytest.approx(500.0)
    # Feature 3: total_spend = gross signed sum (1000 + −500 = 500)
    assert t["total_spend"]   == pytest.approx(500.0)

    # Credit card totals must be isolated from bank rows (Feature 1)
    resp_cc = client.get("/transactions/totals?type=credit_card")
    assert resp_cc.status_code == 200
    tc = resp_cc.json()
    assert tc["row_count"] == 1
    assert tc["total_outflow"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# GET /transactions/sources — Import Source dropdown population
# ---------------------------------------------------------------------------

def test_transactions_sources_endpoint(tmp_path: Path):
    """GET /transactions/sources returns sources scoped by statement_type with counts."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "sources_test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    # Seed two runs
    conn.execute(
        "INSERT INTO runs (run_id, started_at, status, statement_type, run_label, files_count) VALUES "
        "(?, NOW(), 'success', 'bank', 'Chase Checking', 1), "
        "(?, NOW(), 'success', 'credit_card', 'Amex Platinum', 1)",
        ["run_bank_01", "run_cc_01"],
    )
    # Seed transactions linked to runs
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_date, description, amount, currency, bank_name, account_name, "
        " account_id, source_file, source_row, file_hash, transaction_fingerprint, "
        " statement_type, run_id) VALUES "
        "(DATE '2024-01-01','Salary',1000.0,'USD','Chase','Checking','chk01','f.csv',1,'h1','fp1','bank','run_bank_01'),"
        "(DATE '2024-01-02','Coffee',-5.0,'USD','Chase','Checking','chk01','f.csv',2,'h2','fp2','bank','run_bank_01'),"
        "(DATE '2024-01-03','CC charge',-45.0,'USD','Amex','CC','cc01','f.csv',3,'h3','fp3','credit_card','run_cc_01')"
    )
    conn.close()

    # bank sources — only bank run should appear
    r = client.get("/transactions/sources?type=bank")
    assert r.status_code == 200
    sources = r.json()["sources"]
    assert len(sources) == 1
    assert sources[0]["id"] == "run_bank_01"
    assert sources[0]["label"] == "Chase Checking"
    assert sources[0]["count"] == 2

    # credit_card sources — only CC run should appear (Feature 1 isolation)
    r2 = client.get("/transactions/sources?type=credit_card")
    assert r2.status_code == 200
    sources2 = r2.json()["sources"]
    assert len(sources2) == 1
    assert sources2[0]["id"] == "run_cc_01"
    assert sources2[0]["count"] == 1


def test_transactions_source_filter(tmp_path: Path):
    """GET /transactions?source=<run_id> returns only rows from that specific import."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "src_filter_test.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO transactions_norm "
        "(transaction_date, description, amount, currency, bank_name, account_name, "
        " account_id, source_file, source_row, file_hash, transaction_fingerprint, "
        " statement_type, run_id) VALUES "
        "(DATE '2024-02-01','Run A txn 1',100.0,'USD','Bank','Chk','chk01','a.csv',1,'h1','fp1','bank','run_a'),"
        "(DATE '2024-02-02','Run B txn 1',200.0,'USD','Bank','Chk','chk01','b.csv',2,'h2','fp2','bank','run_b')"
    )
    conn.close()

    # source=run_a should only return the one row from run_a
    r = client.get("/transactions?type=bank&source=run_a")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["description"] == "Run A txn 1"

    # source=all returns both rows
    r2 = client.get("/transactions?type=bank&source=all")
    assert r2.status_code == 200
    assert r2.json()["count"] == 2

    # totals scoped by source
    r3 = client.get("/transactions/totals?type=bank&source=run_b")
    assert r3.status_code == 200
    assert r3.json()["total_income"] == pytest.approx(200.0)


def test_transactions_sources_empty(tmp_path: Path):
    """GET /transactions/sources with no matching data returns empty list."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "sources_empty.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    r = client.get("/transactions/sources?type=credit_card")
    assert r.status_code == 200
    assert r.json()["sources"] == []


def test_transactions_sources_no_type_param_does_not_crash(tmp_path: Path):
    """
    BUG FIX: GET /transactions/sources with no type param must return 200, not 500.

    Root cause: the SQL previously had 'AND r.status IN (...)' appended to an
    empty where_sql, producing invalid SQL ('JOIN ... AND ...') with no WHERE.
    Fix: status filter is now the first condition in the WHERE list, always present.
    """
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "sources_no_type.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Must not raise a 500 — previously crashed with a SQL syntax error
    r = client.get("/transactions/sources")
    assert r.status_code == 200, f"Expected 200 but got {r.status_code}: {r.text}"
    assert "sources" in r.json()


# ---------------------------------------------------------------------------
# BUG FIX 1: statement_type must be routed correctly through wizard pipeline
# ---------------------------------------------------------------------------

def test_wizard_statement_type_credit_card_routing(tmp_path: Path):
    """
    BUG FIX 1: POST /wizard/save-and-run with statement_type='credit_card' must
    produce transaction rows with statement_type='credit_card', never 'bank' or NULL.

    Layer 3 — backend persistence: statement_type is read from the request,
    written to every transaction row in transactions_norm.
    """
    import csv as _csv
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "wizard_cc_routing.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    # Minimal CSV with a signed amount
    csv_path = tmp_path / "cc.csv"
    with open(csv_path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["Date", "Description", "Amount"])
        w.writerow(["2024-01-15", "Starbucks", "-5.50"])
        w.writerow(["2024-01-16", "Amazon",    "-42.00"])

    # Upload
    with open(csv_path, "rb") as fh:
        up = client.post("/upload", files={"file": ("cc.csv", fh, "text/csv")})
    assert up.status_code == 200, up.text

    # Save-and-run with statement_type='credit_card', preview_only=False
    res = client.post("/wizard/save-and-run", json={
        "file_paths":      [up.json()["path"]],
        "canonical_map":   {"transaction_date": "Date", "description": "Description", "amount": "Amount"},
        "institution":     "testbank",
        "account_id":      "cc1234",
        "account_name":    "My Credit Card",
        "bank_name":       "TestBank",
        "date_format":     "%Y-%m-%d",
        "preview_only":    False,
        "statement_type":  "credit_card",   # BUG FIX 1: must be respected
    })
    assert res.status_code in (200, 202), res.text
    run_id = res.json()["run_id"]

    # Poll until done
    import time
    for _ in range(30):
        st = client.get(f"/runs/{run_id}")
        if st.json().get("status") in ("success", "failed"):
            break
        time.sleep(0.2)
    assert st.json()["status"] == "success", st.json()

    # Layer 4: credit_card query must return our rows
    r_cc = client.get("/transactions?type=credit_card")
    assert r_cc.status_code == 200
    cc_rows = r_cc.json()["rows"]
    assert len(cc_rows) >= 1, "credit_card tab must see rows imported as credit_card"
    assert all(r.get("statement_type") == "credit_card" for r in cc_rows), \
        "All credit_card rows must have statement_type='credit_card'"

    # Layer 4: bank query must NOT include our rows
    r_bank = client.get("/transactions?type=bank")
    assert r_bank.status_code == 200
    bank_rows = r_bank.json()["rows"]
    our_descs = {"Starbucks", "Amazon"}
    leaked = [r for r in bank_rows if r.get("description") in our_descs]
    assert not leaked, f"credit_card rows must not appear in bank tab: {leaked}"


def test_wizard_statement_type_bank_routing(tmp_path: Path):
    """
    BUG FIX 1: POST /wizard/save-and-run with statement_type='bank' must
    produce transaction rows with statement_type='bank', never 'credit_card' or NULL.
    """
    import csv as _csv
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "wizard_bank_routing.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    csv_path = tmp_path / "bank.csv"
    with open(csv_path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["Date", "Description", "Amount"])
        w.writerow(["2024-02-01", "Salary",     "3000.00"])
        w.writerow(["2024-02-05", "Rent",       "-1200.00"])

    with open(csv_path, "rb") as fh:
        up = client.post("/upload", files={"file": ("bank.csv", fh, "text/csv")})
    assert up.status_code == 200, up.text

    res = client.post("/wizard/save-and-run", json={
        "file_paths":      [up.json()["path"]],
        "canonical_map":   {"transaction_date": "Date", "description": "Description", "amount": "Amount"},
        "institution":     "testbank",
        "account_id":      "chk1234",
        "account_name":    "My Checking",
        "bank_name":       "TestBank",
        "date_format":     "%Y-%m-%d",
        "preview_only":    False,
        "statement_type":  "bank",   # BUG FIX 1: must be respected
    })
    assert res.status_code in (200, 202), res.text
    run_id = res.json()["run_id"]

    import time
    for _ in range(30):
        st = client.get(f"/runs/{run_id}")
        if st.json().get("status") in ("success", "failed"):
            break
        time.sleep(0.2)
    assert st.json()["status"] == "success", st.json()

    r_bank = client.get("/transactions?type=bank")
    assert r_bank.status_code == 200
    bank_rows = r_bank.json()["rows"]
    assert len(bank_rows) >= 1, "bank tab must see rows imported as bank"
    assert all(r.get("statement_type") == "bank" for r in bank_rows), \
        "All bank rows must have statement_type='bank'"

    r_cc = client.get("/transactions?type=credit_card")
    assert r_cc.status_code == 200
    cc_rows = r_cc.json()["rows"]
    our_descs = {"Salary", "Rent"}
    leaked = [r for r in cc_rows if r.get("description") in our_descs]
    assert not leaked, f"bank rows must not appear in credit_card tab: {leaked}"


# ---------------------------------------------------------------------------
# BUG FIX 3: amount_debit / amount_credit as canonical fields in wizard pipeline
# ---------------------------------------------------------------------------

def test_resolve_amount_empty_string_treated_as_absent():
    """
    BUG FIX 3: amount = empty string must be treated as absent, falling back
    to amount_debit / amount_credit.  (Same as null amount for signed family.)
    """
    from decimal import Decimal
    from finance_etl.normalize import resolve_amount

    row = {
        "amount_raw":        "",         # empty string = absent
        "debit_raw":         "",
        "credit_raw":        "",
        "money_in_raw":      "",
        "money_out_raw":     "",
        "amount_debit_raw":  "50.00",    # outflow → stored negative
        "amount_credit_raw": "100.00",   # inflow  → stored positive
        "source_row": 1, "source_file": "t.csv",
    }
    result = resolve_amount(row, "signed", {}, {})
    assert result == Decimal("50.00"), f"Expected 100-50=50, got {result}"


def test_resolve_amount_debit_credit_via_wizard_canonical(tmp_path: Path):
    """
    BUG FIX 3 integration: wizard_to_pipeline_mapping with amount_debit+amount_credit
    produces a mapping dict that, when run through run_with_options, stores the
    correct signed amount (credit − debit) in transactions_norm.
    """
    import csv as _csv
    from decimal import Decimal
    from finance_etl.wizard_mapping import wizard_to_pipeline_mapping
    from finance_etl.pipeline import run_with_options
    from finance_etl.db import get_connection

    # CSV with separate debit/credit columns (positive numbers)
    csv_path = tmp_path / "amtdc.csv"
    with open(csv_path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["Date", "Description", "Debit", "Credit"])
        w.writerow(["2024-03-01", "Coffee",    "4.50", ""])      # outflow
        w.writerow(["2024-03-05", "Paycheck",  "",     "2000.00"])  # inflow

    db_path = tmp_path / "amtdc.duckdb"

    # Build a pipeline mapping dict via wizard_to_pipeline_mapping
    mapping_dict = wizard_to_pipeline_mapping(
        canonical_map={
            "transaction_date": "Date",
            "description":      "Description",
            "amount_debit":     "Debit",    # BUG FIX 3 canonical field
            "amount_credit":    "Credit",   # BUG FIX 3 canonical field
        },
        bank_name="TestBank",
        bank_key="testbank",
        account_name="Fallback Test",
        account_id="amtdc01",
        date_format="%Y-%m-%d",
    )
    # Confirm amount_debit / amount_credit flowed into the amount config
    assert mapping_dict["amount"].get("amount_debit")  == "Debit"
    assert mapping_dict["amount"].get("amount_credit") == "Credit"

    # Run the pipeline — statement_type='bank' so rows appear in bank tab
    run_with_options(
        inputs=[str(csv_path)],
        db_path=str(db_path),
        mapping_dict=mapping_dict,
        statement_type="bank",
    )

    # Verify stored amounts: Coffee outflow = -4.50, Paycheck inflow = +2000
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT description, amount FROM transactions_norm ORDER BY transaction_date"
    ).fetchall()
    conn.close()

    assert rows, "Expected at least one row in transactions_norm"
    by_desc = {desc: float(amt) for desc, amt in rows}
    assert by_desc.get("Coffee")   == pytest.approx(-4.50,   abs=0.01), \
        f"Coffee outflow must be stored as -4.50; got {by_desc.get('Coffee')}"
    assert by_desc.get("Paycheck") == pytest.approx(2000.00, abs=0.01), \
        f"Paycheck inflow must be stored as +2000; got {by_desc.get('Paycheck')}"


def test_amount_debit_credit_in_canonical_fields():
    """
    BUG FIX 3: amount_debit and amount_credit must appear in CANONICAL_FIELDS
    and CANONICAL_LABELS, and form a valid AMOUNT_GROUP.
    """
    from finance_etl.wizard_mapping import (
        CANONICAL_FIELDS, CANONICAL_LABELS, AMOUNT_GROUPS, validate_wizard_mapping
    )

    assert "amount_debit"  in CANONICAL_FIELDS, "amount_debit missing from CANONICAL_FIELDS"
    assert "amount_credit" in CANONICAL_FIELDS, "amount_credit missing from CANONICAL_FIELDS"
    assert "amount_debit"  in CANONICAL_LABELS, "amount_debit missing from CANONICAL_LABELS"
    assert "amount_credit" in CANONICAL_LABELS, "amount_credit missing from CANONICAL_LABELS"
    assert {"amount_debit", "amount_credit"} in AMOUNT_GROUPS, \
        "{'amount_debit','amount_credit'} must be a valid AMOUNT_GROUP"

    # Validate that mapping only amount_debit + amount_credit passes validation
    errors = validate_wizard_mapping({
        "transaction_date": "Date",
        "amount_debit":     "Debit",
        "amount_credit":    "Credit",
    })
    assert errors == [], f"amount_debit+amount_credit should form a valid mapping: {errors}"


def test_wizard_to_pipeline_threads_amount_debit_credit():
    """
    BUG FIX 3: wizard_to_pipeline_mapping must include amount_debit / amount_credit
    in the returned amount config so mapping.py populates amount_debit_raw /
    amount_credit_raw for the normalize.py step 2 fallback.
    """
    from finance_etl.wizard_mapping import wizard_to_pipeline_mapping

    result = wizard_to_pipeline_mapping(
        canonical_map={
            "transaction_date": "Date",
            "amount_debit":     "Debit",
            "amount_credit":    "Credit",
        },
        bank_name="TestBank",
        bank_key="testbank",
        account_name="Checking",
        account_id="chk01",
    )

    assert result["amount"].get("amount_debit")  == "Debit",  \
        "amount_cfg must carry amount_debit CSV column"
    assert result["amount"].get("amount_credit") == "Credit", \
        "amount_cfg must carry amount_credit CSV column"


# ===========================================================================
# FEATURE — Smart CSV Pre-Processing
# ===========================================================================

def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


class TestCsvPreprocessing:
    """Tests for finance_etl.utils.csv_preprocess.preprocess_csv"""

    def test_clean_csv_passes_through_unchanged(self, tmp_path: Path):
        """A standard well-formed CSV must not be modified at all."""
        from finance_etl.utils.csv_preprocess import preprocess_csv

        csv_path = _write_csv(
            tmp_path / "clean.csv",
            "Date,Description,Amount\n2026-01-01,Amazon Prime,29.99\n2026-01-05,Netflix,15.99\n",
        )
        original_text = csv_path.read_text()

        result = preprocess_csv(csv_path)

        assert result["patterns_applied"] == [], "Clean CSV must not trigger any patterns"
        assert result["banner"] is None, "Clean CSV must not produce a UI banner"
        assert csv_path.read_text() == original_text, "Clean CSV file must not be modified"

    def test_pattern1_single_line_header_echo(self, tmp_path: Path):
        """
        Pattern 1: cell value equals the column header exactly.
        The cell should be cleared (or the header stripped).
        """
        from finance_etl.utils.csv_preprocess import preprocess_csv

        # First data row has cells that ARE the header name
        csv_path = _write_csv(
            tmp_path / "echo_single.csv",
            "Date,Description,Amount\nDate,Description,Amount\n2026-01-01,Amazon,29.99\n",
        )

        result = preprocess_csv(csv_path)

        assert any("Date" in p for p in result["patterns_applied"]), \
            "Pattern 1 must be detected for the Date column"
        assert result["banner"] is not None

        rows = list(__import__("csv").reader(csv_path.open()))
        # After stripping, the first data row should not look like the header row
        assert rows[1] != rows[0], "First data row must differ from header after stripping"

    def test_pattern1_multiline_header_echo(self, tmp_path: Path):
        """
        Pattern 1: cell contains 'Header\\nActual Value' — only the header prefix
        should be stripped; the actual value must be preserved.
        """
        from finance_etl.utils.csv_preprocess import preprocess_csv
        import csv as _csv

        # Build CSV with embedded newlines using quoting
        rows = [
            ["Date", "Description", "Amount"],
            ["Date\nFeb 12 2026", "Description\nAMAZON PRIME CONS\nSEATTLE WA", "29.99"],
            ["Feb 13 2026", "Netflix", "15.99"],
        ]
        csv_path = tmp_path / "echo_multiline.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            _csv.writer(fh).writerows(rows)

        result = preprocess_csv(csv_path)

        assert any("Date" in p for p in result["patterns_applied"]), \
            "Pattern 1 must be detected for Date column"
        assert any("Description" in p for p in result["patterns_applied"]), \
            "Pattern 1 must be detected for Description column"

        cleaned = list(_csv.reader(open(csv_path, newline="", encoding="utf-8")))
        # Header row intact
        assert cleaned[0] == ["Date", "Description", "Amount"]
        # First data row: Date column stripped to just the date part
        assert "Feb 12 2026" in cleaned[1][0], \
            f"Date value must be preserved after stripping; got: {cleaned[1][0]!r}"
        # Description: first sub-line label removed, rest joined
        assert "AMAZON PRIME CONS" in cleaned[1][1], \
            f"Description value must be preserved after stripping; got: {cleaned[1][1]!r}"
        assert "Description" not in cleaned[1][1], \
            "Header label 'Description' must be removed from the cell value"

    def test_pattern2_metadata_rows_detected_and_discarded(self, tmp_path: Path):
        """
        Pattern 2: bank metadata rows above the real header are discarded.
        The header is identified by canonical field synonym matching.
        """
        from finance_etl.utils.csv_preprocess import preprocess_csv
        import csv as _csv

        csv_content = (
            "Barclays Bank Delaware\n"
            "Account Number: XXXX1234\n"
            "Account Balance as of Feb 2026,1234.56\n"
            "\n"
            "Transaction Date,Description,Category,Amount\n"
            "2026-02-12,AMAZON PRIME,Shopping,-14.99\n"
            "2026-02-14,NETFLIX,Entertainment,-15.99\n"
        )
        csv_path = _write_csv(tmp_path / "barclays.csv", csv_content)

        result = preprocess_csv(csv_path)

        assert any("metadata" in p.lower() or "skipped" in p.lower()
                   for p in result["patterns_applied"]), \
            f"Pattern 2 must be detected; patterns_applied={result['patterns_applied']}"

        # Real header must be the first row in the cleaned file
        cleaned_rows = list(_csv.reader(open(csv_path, newline="", encoding="utf-8")))
        assert cleaned_rows[0][0] in ("Transaction Date", "transaction date"), \
            f"First row of cleaned file must be the real header; got: {cleaned_rows[0]}"

        # Data rows must remain
        assert len(cleaned_rows) >= 3, "Transaction rows must be preserved"

        # statement_meta must capture pre-header metadata
        assert result["metadata"], "statement_meta must not be empty when metadata rows exist"
        assert result["banner"] is not None, "A UI banner must be produced for Pattern 2"

    def test_statement_meta_captured_not_lost(self, tmp_path: Path):
        """
        Pre-header metadata (bank name, account number) must appear in
        result['metadata'] — not silently discarded.
        """
        from finance_etl.utils.csv_preprocess import preprocess_csv

        csv_content = (
            "MyBank\n"
            "Account Number,12345678\n"
            "Date,Description,Amount\n"
            "2026-01-01,Coffee,-4.50\n"
        )
        csv_path = _write_csv(tmp_path / "meta.csv", csv_content)

        result = preprocess_csv(csv_path)

        meta = result["metadata"]
        assert meta, "metadata must be non-empty when pre-header rows exist"
        # The bank name row ('MyBank') should appear in some form
        has_bank_name = any("MyBank" in str(v) for v in meta.values())
        assert has_bank_name, f"Bank name must be in statement_meta; got: {meta}"

    def test_pattern2_via_upload_endpoint(self, tmp_path: Path):
        """
        Integration: POST /upload on a Barclays-style CSV must return a
        preprocess_banner and the headers from the real header row (not metadata rows).
        """
        from fastapi.testclient import TestClient
        from finance_etl.api import create_app
        import io

        db_path = tmp_path / "pp_test.duckdb"
        upload_dir = tmp_path / "uploads"
        app = create_app(db_path=str(db_path), upload_dir=str(upload_dir))
        client = TestClient(app)

        csv_content = (
            "Barclays Bank Delaware\n"
            "Account Number: XXXX9999\n"
            "\n"
            "Transaction Date,Description,Amount\n"
            "2026-02-01,Starbucks,-5.75\n"
        ).encode()

        res = client.post(
            "/upload",
            files={"file": ("barclays.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert res.status_code == 200, res.text
        body = res.json()

        assert body.get("preprocess_banner"), \
            "Upload response must include preprocess_banner for Barclays-style CSV"
        # Headers must be from the real header row
        headers = body.get("headers", [])
        assert any("date" in h.lower() for h in headers), \
            f"Real header row must be detected; got headers={headers}"
        # Metadata row strings must NOT appear as headers
        assert not any("barclays" in h.lower() for h in headers), \
            f"Metadata strings must not appear as headers; got headers={headers}"
