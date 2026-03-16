"""Tests for the Accounts & Liabilities module — Phase 1."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from finance_etl.db import get_connection
from finance_etl.accounts.crud import (
    create_account,
    create_payment_source_tag,
    delete_payment_source_tag,
    get_account,
    list_accounts,
    list_payment_source_tags,
    soft_delete_account,
    update_account,
)
from finance_etl.accounts.schemas import AccountCreate, AccountUpdate


@pytest.fixture
def conn():
    """Provide a fresh in-memory-like DuckDB connection with full schema."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.duckdb"
        c = get_connection(str(db_path))
        yield c
        c.close()


# ── Account CRUD ──────────────────────────────────────────────────────


class TestCreateAccount:
    def test_create_credit_card(self, conn):
        data = AccountCreate(
            name="Chase Freedom 4428",
            account_class="liability",
            liability_type="credit_card",
            institution="Chase",
            last_four="4428",
            balance=3015.41,
            credit_limit=12500,
            due_day=7,
        )
        result = create_account(conn, data)
        assert result["name"] == "Chase Freedom 4428"
        assert result["account_class"] == "liability"
        assert result["liability_type"] == "credit_card"
        assert result["account_code"] == "2100"
        assert result["institution"] == "Chase"
        assert result["status"] == "active"
        assert float(result["balance"]) == 3015.41

    def test_create_checking_account(self, conn):
        data = AccountCreate(
            name="SoFi Checking",
            account_class="asset",
            asset_type="checking",
            institution="SoFi",
            balance=5000.00,
            payment_source_tag="sofid",
        )
        result = create_account(conn, data)
        assert result["account_class"] == "asset"
        assert result["asset_type"] == "checking"
        assert result["account_code"] == "1110"
        assert result["is_asset"] is True

    def test_create_mortgage(self, conn):
        data = AccountCreate(
            name="5390 Mortgage",
            account_class="liability",
            liability_type="mortgage",
            institution="FlagStar",
            balance=250000,
            origination_principal=300000,
            interest_rate=4.5,
            loan_term=360,
            escrow_balance=3200,
        )
        result = create_account(conn, data)
        assert result["liability_type"] == "mortgage"
        assert result["account_code"] == "2210"
        assert float(result["interest_rate"]) == 4.5
        assert result["loan_term"] == 360

    def test_create_savings_account(self, conn):
        data = AccountCreate(
            name="AMEX Savings",
            account_class="asset",
            asset_type="savings",
            balance=10000,
        )
        result = create_account(conn, data)
        assert result["account_code"] == "1120"
        assert result["asset_type"] == "savings"

    def test_create_utility(self, conn):
        data = AccountCreate(
            name="We-Energies",
            account_class="liability",
            liability_type="utility",
            due_day=15,
            balance=120,
        )
        result = create_account(conn, data)
        assert result["liability_type"] == "utility"
        assert result["account_code"] == "2300"

    def test_create_personal_debt(self, conn):
        data = AccountCreate(
            name="Xochitl",
            account_class="liability",
            liability_type="personal_debt",
            balance=500,
        )
        result = create_account(conn, data)
        assert result["liability_type"] == "personal_debt"
        assert result["account_code"] == "2400"


class TestCoAAutoAssignment:
    def test_sequential_codes(self, conn):
        for i in range(3):
            data = AccountCreate(
                name=f"Card {i}",
                account_class="liability",
                liability_type="credit_card",
                balance=100 * i,
            )
            result = create_account(conn, data)
            assert result["account_code"] == str(2100 + i)

    def test_different_types_get_different_ranges(self, conn):
        cc = AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=0)
        mortgage = AccountCreate(name="Mortgage", account_class="liability", liability_type="mortgage", balance=0)
        checking = AccountCreate(name="Checking", account_class="asset", asset_type="checking", balance=0)

        cc_result = create_account(conn, cc)
        m_result = create_account(conn, mortgage)
        ch_result = create_account(conn, checking)

        assert cc_result["account_code"] == "2100"
        assert m_result["account_code"] == "2210"
        assert ch_result["account_code"] == "1110"


class TestGetAccount:
    def test_get_existing(self, conn):
        data = AccountCreate(name="Test", account_class="asset", asset_type="checking", balance=100)
        created = create_account(conn, data)
        fetched = get_account(conn, created["id"])
        assert fetched["name"] == "Test"
        assert fetched["id"] == created["id"]

    def test_get_nonexistent(self, conn):
        result = get_account(conn, 99999)
        assert result is None


class TestListAccounts:
    def test_list_all(self, conn):
        create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=0))
        create_account(conn, AccountCreate(name="B", account_class="liability", liability_type="credit_card", balance=0))
        accounts = list_accounts(conn)
        assert len(accounts) == 2

    def test_filter_by_class(self, conn):
        create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=0))
        create_account(conn, AccountCreate(name="B", account_class="liability", liability_type="credit_card", balance=0))
        assets = list_accounts(conn, {"account_class": "asset"})
        assert len(assets) == 1
        assert assets[0]["name"] == "A"

    def test_filter_by_institution(self, conn):
        create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", institution="Chase", balance=0))
        create_account(conn, AccountCreate(name="B", account_class="asset", asset_type="checking", institution="SoFi", balance=0))
        chase = list_accounts(conn, {"institution": "Chase"})
        assert len(chase) == 1

    def test_filter_by_status(self, conn):
        created = create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=0))
        soft_delete_account(conn, created["id"], "closed")
        active = list_accounts(conn, {"status": "active"})
        closed = list_accounts(conn, {"status": "closed"})
        assert len(active) == 0
        assert len(closed) == 1


class TestUpdateAccount:
    def test_update_fields(self, conn):
        data = AccountCreate(name="Old Name", account_class="asset", asset_type="checking", balance=0)
        created = create_account(conn, data)
        updated = update_account(conn, created["id"], AccountUpdate(name="New Name", balance=500))
        assert updated["name"] == "New Name"
        assert float(updated["balance"]) == 500.0

    def test_update_no_changes(self, conn):
        data = AccountCreate(name="Test", account_class="asset", asset_type="checking", balance=100)
        created = create_account(conn, data)
        result = update_account(conn, created["id"], AccountUpdate())
        assert result["name"] == "Test"


class TestSoftDeleteAccount:
    def test_close_account(self, conn):
        data = AccountCreate(name="Test", account_class="asset", asset_type="checking", balance=0)
        created = create_account(conn, data)
        soft_delete_account(conn, created["id"])
        fetched = get_account(conn, created["id"])
        assert fetched["status"] == "closed"

    def test_paid_off_status(self, conn):
        data = AccountCreate(name="Loan", account_class="liability", liability_type="auto_loan", balance=0)
        created = create_account(conn, data)
        soft_delete_account(conn, created["id"], "paid_off")
        fetched = get_account(conn, created["id"])
        assert fetched["status"] == "paid_off"


# ── Payment Source Tags ───────────────────────────────────────────────


class TestPaymentSourceTags:
    def test_create_and_list(self, conn):
        acct = create_account(conn, AccountCreate(name="SoFi", account_class="asset", asset_type="checking", balance=0))
        create_payment_source_tag(conn, "sofid", acct["id"])
        tags = list_payment_source_tags(conn)
        assert len(tags) == 1
        assert tags[0]["short_code"] == "sofid"
        assert tags[0]["account_id"] == acct["id"]

    def test_delete_tag(self, conn):
        acct = create_account(conn, AccountCreate(name="Chase", account_class="asset", asset_type="checking", balance=0))
        create_payment_source_tag(conn, "ch", acct["id"])
        delete_payment_source_tag(conn, "ch")
        tags = list_payment_source_tags(conn)
        assert len(tags) == 0

    def test_multiple_tags(self, conn):
        acct1 = create_account(conn, AccountCreate(name="SoFi", account_class="asset", asset_type="checking", balance=0))
        acct2 = create_account(conn, AccountCreate(name="Chase", account_class="asset", asset_type="checking", balance=0))
        create_payment_source_tag(conn, "sofid", acct1["id"])
        create_payment_source_tag(conn, "ch", acct2["id"])
        tags = list_payment_source_tags(conn)
        assert len(tags) == 2


# ── Validation ────────────────────────────────────────────────────────


class TestValidation:
    def test_invalid_account_class(self):
        with pytest.raises(Exception):
            AccountCreate(name="Bad", account_class="invalid", balance=0)

    def test_due_day_range(self):
        with pytest.raises(Exception):
            AccountCreate(name="Bad", account_class="liability", due_day=32, balance=0)

    def test_due_day_zero(self):
        with pytest.raises(Exception):
            AccountCreate(name="Bad", account_class="liability", due_day=0, balance=0)


# ── Migration Idempotency ────────────────────────────────────────────


class TestMigrationIdempotency:
    def test_migrations_run_twice(self):
        """Running migrations twice should not raise errors."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.duckdb"
            # First run
            c1 = get_connection(str(db_path))
            c1.close()
            # Second run — should not error
            c2 = get_connection(str(db_path))
            c2.close()


# ── Balance Ledger Entry on Create ────────────────────────────────────


class TestBalanceLedgerOnCreate:
    def test_initial_balance_ledger_entry(self, conn):
        data = AccountCreate(
            name="Test Card",
            account_class="liability",
            liability_type="credit_card",
            balance=1500.00,
            statement_balance=1200.00,
        )
        result = create_account(conn, data)
        ledger = conn.execute(
            "SELECT * FROM ap_balance_ledger WHERE account_id = ?",
            [result["id"]],
        ).fetchall()
        assert len(ledger) == 1
        # current_balance is at index 4
        cols = [c[0] for c in conn.execute("SELECT * FROM ap_balance_ledger LIMIT 0").description]
        entry = dict(zip(cols, ledger[0]))
        assert float(entry["current_balance"]) == 1500.00
        assert float(entry["statement_balance"]) == 1200.00
