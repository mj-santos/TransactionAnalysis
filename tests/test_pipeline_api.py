from pathlib import Path
from types import SimpleNamespace

import pytest

from finance_etl.pipeline import chart_from_report_csv, run


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
