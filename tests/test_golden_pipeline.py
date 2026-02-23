import json
from pathlib import Path

from finance_etl.db import get_connection
from finance_etl.ingest import create_run, register_files
from finance_etl.profile import profile_file
from finance_etl.mapping import load_mapping, map_and_stage
from finance_etl.normalize import normalize_staged_rows


def test_golden_csv_to_normalized_output(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(db_path)

    run_id = "goldenrun"
    create_run(conn, run_id, 1)

    fixture_csv = Path("tests/fixtures/golden/signed_weird.csv")
    regs = register_files(conn, [fixture_csv], run_id, tmp_path / "raw")
    reg = regs[0]

    profile_file(conn, reg["file_hash"], reg["ingested_path"], tmp_path / "profiles")

    mapping = load_mapping("config/mappings/example_signed_amount.yaml")
    staged = map_and_stage(conn, reg["ingested_path"], reg["file_hash"], run_id, mapping)
    assert staged == 2

    normalized, errors = normalize_staged_rows(conn, run_id, mapping)
    assert errors == []

    expected = json.loads(Path("tests/fixtures/golden/expected_norm.json").read_text())

    got = [
        {
            "transaction_date": row["transaction_date"].isoformat(),
            "posted_date": row["posted_date"].isoformat() if row["posted_date"] else None,
            "description": row["description"],
            "amount": f"{row['amount']:.2f}",
            "currency": row["currency"],
            "bank_name": row["bank_name"],
            "account_name": row["account_name"],
            "account_id": row["account_id"],
        }
        for row in normalized
    ]

    assert got == expected
    conn.close()
