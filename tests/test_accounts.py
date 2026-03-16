"""Tests for the Accounts & Liabilities module — Phase 1 & 2."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from finance_etl.db import get_connection
from finance_etl.accounts.balance_ops import (
    bulk_balance_update,
    generate_snapshot,
    get_balance_history,
    get_latest_balances,
    get_overview_summary,
    get_stale_accounts,
)
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


# ══════════════════════════════════════════════════════════════════════
# Phase 2 Tests — Balance Operations
# ══════════════════════════════════════════════════════════════════════


class TestBulkBalanceUpdate:
    def test_single_update(self, conn):
        acct = create_account(conn, AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=1000))
        result = bulk_balance_update(conn, [{"account_id": acct["id"], "current_balance": 1500}])
        assert result["updated"] == 1
        fetched = get_account(conn, acct["id"])
        assert float(fetched["balance"]) == 1500.0
        assert fetched["last_verified_at"] is not None

    def test_multiple_updates(self, conn):
        a1 = create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=5000))
        a2 = create_account(conn, AccountCreate(name="B", account_class="liability", liability_type="credit_card", balance=200))
        result = bulk_balance_update(conn, [
            {"account_id": a1["id"], "current_balance": 4500},
            {"account_id": a2["id"], "current_balance": 300, "statement_balance": 250, "minimum_payment": 25},
        ])
        assert result["updated"] == 2
        f2 = get_account(conn, a2["id"])
        assert float(f2["balance"]) == 300.0
        assert float(f2["last_statement_balance"]) == 250.0
        assert float(f2["minimum_payment_amount"]) == 25.0

    def test_skip_unchanged(self, conn):
        """Passing an empty list should update nothing."""
        result = bulk_balance_update(conn, [])
        assert result["updated"] == 0


class TestLedgerImmutability:
    def test_multiple_updates_create_multiple_ledger_entries(self, conn):
        acct = create_account(conn, AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=1000))
        bulk_balance_update(conn, [{"account_id": acct["id"], "current_balance": 1200}])
        bulk_balance_update(conn, [{"account_id": acct["id"], "current_balance": 900}])
        history = get_balance_history(conn, acct["id"])
        # 1 from create + 2 from updates = 3
        assert len(history) == 3
        # Most recent first
        assert float(history[0]["current_balance"]) == 900.0
        assert float(history[1]["current_balance"]) == 1200.0
        assert float(history[2]["current_balance"]) == 1000.0

    def test_balance_history_returns_limited(self, conn):
        acct = create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=0))
        for i in range(5):
            bulk_balance_update(conn, [{"account_id": acct["id"], "current_balance": i * 100}])
        history = get_balance_history(conn, acct["id"], limit=3)
        assert len(history) == 3


class TestSnapshotGeneration:
    def test_snapshot_totals(self, conn):
        create_account(conn, AccountCreate(name="Checking", account_class="asset", asset_type="checking", balance=10000))
        create_account(conn, AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=3000))
        snap = generate_snapshot(conn)
        assert float(snap["total_assets"]) == 10000.0
        assert float(snap["total_liabilities"]) == 3000.0
        assert float(snap["net_worth"]) == 7000.0

    def test_snapshot_inserted_to_db(self, conn):
        create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=5000))
        generate_snapshot(conn)
        rows = conn.execute("SELECT COUNT(*) FROM nw_snapshots").fetchone()
        assert rows[0] >= 1

    def test_bulk_update_generates_snapshot_via_api(self, conn):
        """After bulk_balance_update + generate_snapshot, snapshot exists."""
        create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=5000))
        bulk_balance_update(conn, [])  # no changes, but snapshot is separate
        snap = generate_snapshot(conn)
        assert snap["snapshot_date"] is not None


class TestLatestBalances:
    def test_returns_active_accounts(self, conn):
        create_account(conn, AccountCreate(name="Active", account_class="asset", asset_type="checking", balance=100))
        closed = create_account(conn, AccountCreate(name="Closed", account_class="asset", asset_type="savings", balance=200))
        soft_delete_account(conn, closed["id"], "closed")
        latest = get_latest_balances(conn)
        names = [a["name"] for a in latest]
        assert "Active" in names
        assert "Closed" not in names


class TestStaleDetection:
    def test_never_verified_accounts_are_stale(self, conn):
        # Create an account, then manually null out last_verified_at
        acct = create_account(conn, AccountCreate(name="Stale", account_class="asset", asset_type="checking", balance=0))
        conn.execute("UPDATE nw_accounts SET last_verified_at = NULL WHERE id = ?", [acct["id"]])
        stale = get_stale_accounts(conn, days=1)
        assert len(stale) >= 1
        assert any(s["name"] == "Stale" for s in stale)

    def test_recently_verified_not_stale(self, conn):
        create_account(conn, AccountCreate(name="Fresh", account_class="asset", asset_type="checking", balance=0))
        # Just created = last_verified_at is now, so not stale at 7 days
        stale = get_stale_accounts(conn, days=7)
        assert not any(s["name"] == "Fresh" for s in stale)


class TestOverviewSummary:
    def test_empty_db(self, conn):
        summary = get_overview_summary(conn)
        assert summary["total_assets"] == 0
        assert summary["total_liabilities"] == 0
        assert summary["net_position"] == 0
        assert summary["credit_utilization_pct"] == 0

    def test_with_data(self, conn):
        create_account(conn, AccountCreate(
            name="Checking", account_class="asset", asset_type="checking", balance=10000,
        ))
        create_account(conn, AccountCreate(
            name="CC", account_class="liability", liability_type="credit_card",
            balance=2000, credit_limit=10000, interest_rate=24.99,
        ))
        create_account(conn, AccountCreate(
            name="Debt", account_class="liability", liability_type="personal_debt", balance=500,
        ))
        summary = get_overview_summary(conn)
        assert float(summary["total_assets"]) == 10000.0
        assert float(summary["total_liabilities"]) == 2500.0
        # Excl personal = 2000
        assert float(summary["total_liabilities_excl_personal"]) == 2000.0
        assert float(summary["net_position"]) == 7500.0
        assert summary["credit_utilization_pct"] == 20.0
        assert summary["est_monthly_interest"] > 0
