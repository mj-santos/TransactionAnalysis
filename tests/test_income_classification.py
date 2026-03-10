"""
Tests for income classification fix (BUG-6/7/8).

Rule: True income = amount > 0 AND statement_type = 'bank'.
CC positive amounts (payments, refunds) are never true income.
"""
from pathlib import Path

from finance_etl.db import get_connection


def _seed(conn, rows):
    """Insert rows into transactions_norm for testing."""
    for r in rows:
        conn.execute(
            "INSERT INTO transactions_norm "
            "(transaction_date, description, amount, currency, bank_name, "
            " account_name, account_id, source_file, source_row, file_hash, "
            " transaction_fingerprint, statement_type, transaction_subtype, "
            " resolved_amount) "
            "VALUES (?, ?, ?, 'USD', ?, ?, ?, 'test.csv', ?, 'h1', ?, ?, ?, ?)",
            r,
        )


def test_cc_payment_not_counted_as_income(tmp_path: Path):
    """A CC payment (amount > 0, statement_type='credit_card') must NOT appear
    in any income total — not in Monthly Summary, Cash Flow, or Annual Report."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "cc_income.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    _seed(conn, [
        # CC payment: positive amount, subtype=payment
        ("2025-06-15", "Payment Thank You", 500.00, "Visa", "CC", "cc01",
         1, "fp_cc_pay", "credit_card", "payment", 500.00),
        # CC refund/adjustment: positive amount, subtype=adjustment
        ("2025-06-20", "Refund - Store", 25.00, "Visa", "CC", "cc01",
         2, "fp_cc_ref", "credit_card", "adjustment", 25.00),
        # CC spending: negative amount
        ("2025-06-10", "Amazon Purchase", -80.00, "Visa", "CC", "cc01",
         3, "fp_cc_spend", "credit_card", "spending", 80.00),
    ])
    conn.close()

    # Monthly Summary: income should be 0.0 (CC-only dataset)
    resp = client.post("/monthly-summaries/generate?year=2025&month=6")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_income"] == 0.0, \
        f"Monthly Summary should show $0 income for CC-only data, got {data['summary']['total_income']}"

    # Cash Flow: income should be 0.0
    resp = client.get("/cashflow/summary?period=custom&start_date=2025-06-01&end_date=2025-06-30")
    assert resp.status_code == 200
    cf = resp.json()
    assert cf["summary"]["total_income"] == 0.0, \
        f"Cash Flow should show $0 income for CC-only data, got {cf['total_income']}"

    # Annual Report: income should be 0.0
    resp = client.post("/annual-reports/generate?year=2025")
    assert resp.status_code == 200
    ar = resp.json()
    assert ar["report"]["total_income"] == 0.0, \
        f"Annual Report should show $0 income for CC-only data, got {ar['report']['total_income']}"


def test_bank_deposit_counted_as_income(tmp_path: Path):
    """A bank deposit (amount > 0, statement_type='bank') MUST appear in
    income totals across all three reporting endpoints."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "bank_income.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    _seed(conn, [
        # Bank deposit: positive amount, no subtype (bank rows have NULL subtype)
        ("2025-06-01", "Payroll Deposit", 3000.00, "MyBank", "Checking", "chk01",
         1, "fp_bank_inc", "bank", None, None),
        # Bank expense: negative amount
        ("2025-06-05", "Rent Payment", -1200.00, "MyBank", "Checking", "chk01",
         2, "fp_bank_exp", "bank", None, None),
    ])
    conn.close()

    # Monthly Summary
    resp = client.post("/monthly-summaries/generate?year=2025&month=6")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_income"] == 3000.0, \
        f"Monthly Summary should show $3000 income, got {data['summary']['total_income']}"

    # Cash Flow
    resp = client.get("/cashflow/summary?period=custom&start_date=2025-06-01&end_date=2025-06-30")
    assert resp.status_code == 200
    cf = resp.json()
    assert cf["summary"]["total_income"] == 3000.0, \
        f"Cash Flow should show $3000 income, got {cf['total_income']}"

    # Annual Report
    resp = client.post("/annual-reports/generate?year=2025")
    assert resp.status_code == 200
    ar = resp.json()
    assert ar["report"]["total_income"] == 3000.0, \
        f"Annual Report should show $3000 income, got {ar['report']['total_income']}"


def test_summary_and_cashflow_income_match(tmp_path: Path):
    """With a mixed dataset (bank + CC), Monthly Summary and Cash Flow must
    return identical income figures for the same month."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "match_income.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    _seed(conn, [
        # Bank deposit (real income)
        ("2025-06-01", "Payroll", 3000.00, "MyBank", "Checking", "chk01",
         1, "fp_salary", "bank", None, None),
        # Bank expense
        ("2025-06-10", "Grocery Store", -150.00, "MyBank", "Checking", "chk01",
         2, "fp_grocery", "bank", None, None),
        # CC payment (NOT income)
        ("2025-06-15", "Payment Thank You", 500.00, "Visa", "CC", "cc01",
         3, "fp_cc_pay2", "credit_card", "payment", 500.00),
        # CC spending
        ("2025-06-20", "Restaurant", -45.00, "Visa", "CC", "cc01",
         4, "fp_cc_rest", "credit_card", "spending", 45.00),
        # CC refund (NOT income)
        ("2025-06-25", "Store Refund", 20.00, "Visa", "CC", "cc01",
         5, "fp_cc_refund", "credit_card", "adjustment", 20.00),
    ])
    conn.close()

    # Monthly Summary
    resp = client.post("/monthly-summaries/generate?year=2025&month=6")
    assert resp.status_code == 200
    summary_income = resp.json()["summary"]["total_income"]

    # Cash Flow (same month, same date range)
    resp = client.get("/cashflow/summary?period=custom&start_date=2025-06-01&end_date=2025-06-30")
    assert resp.status_code == 200
    cashflow_income = resp.json()["summary"]["total_income"]

    assert summary_income == cashflow_income == 3000.0, (
        f"Summary ({summary_income}) and Cash Flow ({cashflow_income}) "
        f"must both equal $3000 (bank deposit only)"
    )


def test_custom_report_income_filter(tmp_path: Path):
    """POST /reports/query with group_by must only count bank deposits as income.
    CC positive amounts (payments, refunds) must be excluded from total_income."""
    from fastapi.testclient import TestClient
    from finance_etl.api import create_app

    db_path = tmp_path / "report_income.duckdb"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)

    conn = get_connection(db_path)
    _seed(conn, [
        # Bank deposits (should be income)
        ("2025-06-01", "Payroll", 3000.00, "MyBank", "Checking", "chk01",
         1, "fp_pay1", "bank", None, None),
        ("2025-06-15", "Freelance", 500.00, "MyBank", "Checking", "chk01",
         2, "fp_pay2", "bank", None, None),
        # Bank expenses (should NOT be income)
        ("2025-06-05", "Rent", -1200.00, "MyBank", "Checking", "chk01",
         3, "fp_rent", "bank", None, None),
        ("2025-06-10", "Groceries", -80.00, "MyBank", "Checking", "chk01",
         4, "fp_groc", "bank", None, None),
        # CC payment (positive, should NOT be income)
        ("2025-06-20", "Payment Thank You", 600.00, "Visa", "CC", "cc01",
         5, "fp_ccpay", "credit_card", "payment", 600.00),
        # CC refund (positive, should NOT be income)
        ("2025-06-22", "Refund", 50.00, "Visa", "CC", "cc01",
         6, "fp_ccref", "credit_card", "adjustment", 50.00),
        # CC spending (negative, should NOT be income)
        ("2025-06-25", "Store", -75.00, "Visa", "CC", "cc01",
         7, "fp_ccstore", "credit_card", "spending", 75.00),
    ])
    conn.close()

    # Grouped query on statement_type to get totals per type
    resp = client.post("/reports/query", json={
        "group_by": ["statement_type"],
        "filters": [
            {"field": "transaction_date", "op": ">=", "value": "2025-06-01"},
            {"field": "transaction_date", "op": "<=", "value": "2025-06-30"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    rows = data["rows"]

    # Sum total_income across all groups
    total_income = sum(float(r["total_income"]) for r in rows)
    assert total_income == 3500.0, (
        f"Custom report total_income should be $3500 (bank deposits only), got {total_income}"
    )

    # Bank row should have income = 3500
    bank_row = [r for r in rows if r["statement_type"] == "bank"]
    assert len(bank_row) == 1
    assert float(bank_row[0]["total_income"]) == 3500.0

    # CC row should have income = 0
    cc_row = [r for r in rows if r["statement_type"] == "credit_card"]
    assert len(cc_row) == 1
    assert float(cc_row[0]["total_income"]) == 0.0, (
        f"CC total_income should be $0, got {cc_row[0]['total_income']}"
    )


def test_income_filter_constant_unchanged():
    """Tripwire test — if INCOME_FILTER changes, this test fails immediately.
    Any change to the income classification rule must be a conscious decision."""
    from finance_etl.utils.query_helpers import INCOME_FILTER

    assert INCOME_FILTER == "amount > 0 AND statement_type = 'bank'"
