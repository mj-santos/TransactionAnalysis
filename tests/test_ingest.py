from pathlib import Path

import pytest

from finance_etl.db import get_connection
from finance_etl.ingest import create_run, finalize_run, register_files


def test_register_files_avoids_same_name_collision(tmp_path: Path):
    left = tmp_path / "a"
    right = tmp_path / "b"
    left.mkdir()
    right.mkdir()

    src1 = left / "transactions.csv"
    src2 = right / "transactions.csv"
    src1.write_text("h\n1\n")
    src2.write_text("h\n2\n")

    conn = get_connection(tmp_path / "test.duckdb")
    run_id = "runx"
    create_run(conn, run_id, 2)

    regs = register_files(conn, [src1, src2], run_id, tmp_path / "raw")
    assert regs[0]["ingested_path"] != regs[1]["ingested_path"]


def test_finalize_run_rejects_invalid_status(tmp_path: Path):
    conn = get_connection(tmp_path / "test.duckdb")
    create_run(conn, "r1", 1)

    with pytest.raises(ValueError, match="Invalid run status"):
        finalize_run(conn, "r1", "done", {}, notes="")
