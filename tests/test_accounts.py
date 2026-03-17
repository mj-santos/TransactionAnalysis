"""Tests for the Accounts & Liabilities module — Phases 1–7."""
from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

import pytest

from finance_etl.db import get_connection
from finance_etl.accounts.import_wizard import (
    _parse_number,
    commit_import,
    infer_account_type,
    preview_import,
    suggest_account_mappings,
)
from finance_etl.accounts.cross_module import (
    annual_fee_cross_reference,
    get_utilization_alerts,
    spending_vs_statement,
    suggested_liabilities,
    verify_payment,
)
from finance_etl.accounts.analytics import (
    get_aggregate_debt_trend,
    get_annual_fees,
    get_balance_trends,
    get_benefits_value,
    get_interest_cost,
    get_payoff_projection,
    get_payment_history_summary,
    get_upcoming_due,
    get_utilization_breakdown,
)
from finance_etl.accounts.balance_ops import (
    bulk_balance_update,
    generate_snapshot,
    get_balance_history,
    get_latest_balances,
    get_overview_summary,
    get_stale_accounts,
)
from finance_etl.accounts.billing_cycles import (
    create_billing_cycle,
    get_billing_cycle,
    get_open_cycles,
    get_overdue_cycles,
    list_cycles_for_account,
    update_billing_cycle,
    update_cycle_payment_status,
)
from finance_etl.accounts.crud import (
    bulk_delete_accounts,
    create_account,
    create_payment_source_tag,
    delete_payment_source_tag,
    get_account,
    get_delete_impact,
    hard_delete_account,
    list_accounts,
    list_payment_source_tags,
    soft_delete_account,
    update_account,
)
from finance_etl.accounts.payment_plan import (
    get_capacity,
    get_payment_plan,
    rollforward_plan,
    upsert_plan_assignment,
)
from finance_etl.accounts.payments import (
    get_payment_history,
    record_payment,
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


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: Billing Cycles, Payment Planning, Payments
# ═══════════════════════════════════════════════════════════════════════


def _make_cc_and_checking(conn):
    """Helper: create a credit card and checking account."""
    cc = create_account(conn, AccountCreate(
        name="Test CC", account_class="liability", liability_type="credit_card",
        balance=1500, credit_limit=5000, due_day=15,
    ))
    checking = create_account(conn, AccountCreate(
        name="Test Checking", account_class="asset", asset_type="checking", balance=10000,
    ))
    return cc, checking


class TestBillingCycles:
    def test_create_billing_cycle(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        cycle = create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1200.50,
            "payment_due_date": "2026-04-15",
            "minimum_payment": 35.00,
        })
        assert cycle["account_id"] == cc["id"]
        assert cycle["cycle_label"] == "2026-03"
        assert float(cycle["statement_balance"]) == 1200.50
        assert cycle["status"] == "open"
        assert float(cycle["total_paid"]) == 0

    def test_creates_updates_account_statement_fields(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1200.50,
            "payment_due_date": "2026-04-15",
            "minimum_payment": 35.00,
            "statement_close_date": "2026-03-10",
        })
        acct = get_account(conn, cc["id"])
        assert float(acct["last_statement_balance"]) == 1200.50
        assert float(acct["minimum_payment_amount"]) == 35.00
        assert acct["next_payment_due_date"] == "2026-04-15"

    def test_list_cycles_for_account(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        create_billing_cycle(conn, {"account_id": cc["id"], "cycle_label": "2026-02", "statement_balance": 800, "payment_due_date": "2026-03-15"})
        create_billing_cycle(conn, {"account_id": cc["id"], "cycle_label": "2026-03", "statement_balance": 1200, "payment_due_date": "2026-04-15"})
        cycles = list_cycles_for_account(conn, cc["id"])
        assert len(cycles) == 2
        assert cycles[0]["cycle_label"] == "2026-03"  # most recent first

    def test_update_billing_cycle(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        cycle = create_billing_cycle(conn, {"account_id": cc["id"], "cycle_label": "2026-03", "statement_balance": 1000, "payment_due_date": "2026-04-15"})
        updated = update_billing_cycle(conn, cycle["id"], {"statement_balance": 1100})
        assert float(updated["statement_balance"]) == 1100.0

    def test_get_open_cycles(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        create_billing_cycle(conn, {"account_id": cc["id"], "cycle_label": "2026-03", "statement_balance": 1000, "payment_due_date": "2026-04-15"})
        cycles = get_open_cycles(conn)
        assert len(cycles) >= 1
        assert cycles[0]["status"] == "open"

    def test_get_overdue_cycles(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2025-01",
            "statement_balance": 500,
            "payment_due_date": "2025-02-15",
        })
        overdue = get_overdue_cycles(conn)
        assert len(overdue) >= 1


class TestCyclePaymentStatus:
    def test_paid_full_status(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        cycle = create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 100,
            "payment_due_date": "2026-04-15",
            "minimum_payment": 25,
        })
        # Simulate paying in full
        conn.execute("UPDATE ap_billing_cycles SET total_paid = 100 WHERE id = ?", [cycle["id"]])
        result = update_cycle_payment_status(conn, cycle["id"])
        assert result["status"] == "paid_full"

    def test_paid_minimum_status(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        cycle = create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1000,
            "payment_due_date": "2026-04-15",
            "minimum_payment": 25,
        })
        conn.execute("UPDATE ap_billing_cycles SET total_paid = 25 WHERE id = ?", [cycle["id"]])
        result = update_cycle_payment_status(conn, cycle["id"])
        assert result["status"] == "paid_minimum"

    def test_still_open_status(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        cycle = create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1000,
            "payment_due_date": "2026-04-15",
            "minimum_payment": 25,
        })
        result = update_cycle_payment_status(conn, cycle["id"])
        assert result["status"] == "open"


class TestPaymentPlan:
    def test_upsert_creates_assignment(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        result = upsert_plan_assignment(conn, {
            "liability_id": cc["id"],
            "source_id": checking["id"],
            "cycle_month": "2026-03",
            "planned_amount": 1200.50,
            "strategy": "statement",
        })
        assert result["liability_id"] == cc["id"]
        assert result["source_id"] == checking["id"]
        assert float(result["planned_amount"]) == 1200.50
        assert result["status"] == "planned"

    def test_upsert_updates_existing(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 1000, "strategy": "statement",
        })
        updated = upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 1500, "strategy": "full_balance",
        })
        assert float(updated["planned_amount"]) == 1500.0
        assert updated["strategy"] == "full_balance"
        # Should be only one row
        plan = get_payment_plan(conn, "2026-03")
        assert len(plan) == 1

    def test_get_payment_plan(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 500,
        })
        plan = get_payment_plan(conn, "2026-03")
        assert len(plan) == 1
        assert plan[0]["liability_id"] == cc["id"]


class TestCapacity:
    def test_capacity_with_no_allocations(self, conn):
        _, checking = _make_cc_and_checking(conn)
        capacity = get_capacity(conn, "2026-03")
        checking_cap = [c for c in capacity if c["id"] == checking["id"]]
        assert len(checking_cap) == 1
        assert checking_cap[0]["total_allocated"] == 0
        assert checking_cap[0]["remaining_after_payments"] == 10000.0

    def test_capacity_with_allocations(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 3000,
        })
        capacity = get_capacity(conn, "2026-03")
        checking_cap = [c for c in capacity if c["id"] == checking["id"]]
        assert checking_cap[0]["total_allocated"] == 3000.0
        assert checking_cap[0]["remaining_after_payments"] == 7000.0

    def test_capacity_excludes_skipped(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 2000, "status": "skipped",
        })
        capacity = get_capacity(conn, "2026-03")
        checking_cap = [c for c in capacity if c["id"] == checking["id"]]
        assert checking_cap[0]["total_allocated"] == 0  # skipped doesn't count


class TestRollforward:
    def test_rollforward_copies_assignments(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-02", "planned_amount": 1000, "strategy": "statement",
        })
        result = rollforward_plan(conn, "2026-02", "2026-03")
        assert result["created"] == 1
        assert result["skipped"] == 0
        plan = get_payment_plan(conn, "2026-03")
        assert len(plan) == 1
        assert plan[0]["strategy"] == "statement"
        assert plan[0]["status"] == "planned"

    def test_rollforward_skips_existing(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-02", "planned_amount": 1000,
        })
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 500,
        })
        result = rollforward_plan(conn, "2026-02", "2026-03")
        assert result["created"] == 0
        assert result["skipped"] == 1


class TestRecordPayment:
    def test_record_payment_basic(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        payment = record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 500.00,
        })
        assert payment["from_account_id"] == checking["id"]
        assert payment["to_account_id"] == cc["id"]
        assert float(payment["amount"]) == 500.0

    def test_payment_updates_last_payment_on_account(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 200.00,
        })
        acct = get_account(conn, cc["id"])
        assert acct["last_payment_date"] == "2026-03-10"
        assert float(acct["last_payment_amount"]) == 200.0

    def test_payment_updates_billing_cycle(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        cycle = create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1000,
            "payment_due_date": "2026-04-15",
            "minimum_payment": 25,
        })
        record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 1000.00,
            "billing_cycle_id": cycle["id"],
        })
        updated_cycle = get_billing_cycle(conn, cycle["id"])
        assert float(updated_cycle["total_paid"]) == 1000.0
        assert updated_cycle["status"] == "paid_full"

    def test_payment_sets_plan_in_progress(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        upsert_plan_assignment(conn, {
            "liability_id": cc["id"], "source_id": checking["id"],
            "cycle_month": "2026-03", "planned_amount": 1000,
        })
        record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 500.00,
        })
        plan = get_payment_plan(conn, "2026-03")
        assert plan[0]["status"] == "in_progress"


class TestPaymentHistory:
    def test_get_all_history(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        record_payment(conn, {"from_account_id": checking["id"], "to_account_id": cc["id"], "payment_date": "2026-03-01", "amount": 100})
        record_payment(conn, {"from_account_id": checking["id"], "to_account_id": cc["id"], "payment_date": "2026-03-05", "amount": 200})
        history = get_payment_history(conn)
        assert len(history) == 2
        assert float(history[0]["amount"]) == 200.0  # most recent first

    def test_filter_by_account(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        cc2 = create_account(conn, AccountCreate(name="CC2", account_class="liability", liability_type="credit_card", balance=500))
        record_payment(conn, {"from_account_id": checking["id"], "to_account_id": cc["id"], "payment_date": "2026-03-01", "amount": 100})
        record_payment(conn, {"from_account_id": checking["id"], "to_account_id": cc2["id"], "payment_date": "2026-03-02", "amount": 200})
        history = get_payment_history(conn, account_id=cc["id"])
        assert len(history) == 1
        assert history[0]["to_account_id"] == cc["id"]


# ═══════════════════════════════════════════════════════════════════════
# Phase 4: Analytics & Trends
# ═══════════════════════════════════════════════════════════════════════


class TestUtilizationBreakdown:
    def test_empty_db(self, conn):
        result = get_utilization_breakdown(conn)
        assert result["cards"] == []
        assert result["aggregate"]["utilization_pct"] == 0

    def test_single_card(self, conn):
        create_account(conn, AccountCreate(
            name="CC", account_class="liability", liability_type="credit_card",
            balance=2000, credit_limit=10000,
        ))
        result = get_utilization_breakdown(conn)
        assert len(result["cards"]) == 1
        assert result["cards"][0]["utilization_pct"] == 20.0
        assert result["aggregate"]["utilization_pct"] == 20.0
        assert result["aggregate"]["available_credit"] == 8000.0

    def test_multiple_cards(self, conn):
        create_account(conn, AccountCreate(name="CC1", account_class="liability", liability_type="credit_card", balance=3000, credit_limit=10000))
        create_account(conn, AccountCreate(name="CC2", account_class="liability", liability_type="credit_card", balance=7000, credit_limit=10000))
        result = get_utilization_breakdown(conn)
        assert len(result["cards"]) == 2
        assert result["aggregate"]["utilization_pct"] == 50.0

    def test_excludes_closed(self, conn):
        cc = create_account(conn, AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=5000, credit_limit=10000))
        soft_delete_account(conn, cc["id"], "closed")
        result = get_utilization_breakdown(conn)
        assert len(result["cards"]) == 0


class TestInterestCost:
    def test_empty_db(self, conn):
        result = get_interest_cost(conn)
        assert result["accounts"] == []
        assert result["total_monthly_interest"] == 0

    def test_with_apr(self, conn):
        create_account(conn, AccountCreate(
            name="CC", account_class="liability", liability_type="credit_card",
            balance=12000, interest_rate=24,
        ))
        result = get_interest_cost(conn)
        assert len(result["accounts"]) == 1
        # 12000 * 24% / 12 = 240
        assert result["total_monthly_interest"] == 240.0
        assert result["total_annual_interest"] == 2880.0

    def test_excludes_zero_rate(self, conn):
        create_account(conn, AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=5000))
        result = get_interest_cost(conn)
        assert len(result["accounts"]) == 0


class TestPayoffProjection:
    def test_empty_db(self, conn):
        result = get_payoff_projection(conn, "minimum")
        assert result == []

    def test_zero_interest_payoff(self, conn):
        create_account(conn, AccountCreate(
            name="Loan", account_class="liability", liability_type="personal_debt",
            balance=1000, minimum_payment_amount=None,
        ))
        # With 0 APR and no min payment, pays off in 1 month
        result = get_payoff_projection(conn, "minimum")
        assert len(result) == 1
        assert result[0]["months_to_payoff"] == 1
        assert result[0]["total_interest"] == 0

    def test_with_interest(self, conn):
        create_account(conn, AccountCreate(
            name="CC", account_class="liability", liability_type="credit_card",
            balance=1000, interest_rate=24,
        ))
        conn.execute("UPDATE nw_accounts SET minimum_payment_amount = 50 WHERE name = 'CC'")
        result = get_payoff_projection(conn, "minimum")
        assert len(result) == 1
        assert result[0]["months_to_payoff"] is not None
        assert result[0]["months_to_payoff"] > 12  # Takes more than a year with min payment
        assert result[0]["total_interest"] > 0

    def test_strategies(self, conn):
        create_account(conn, AccountCreate(
            name="CC", account_class="liability", liability_type="credit_card",
            balance=5000, interest_rate=20, credit_limit=10000,
        ))
        conn.execute("UPDATE nw_accounts SET minimum_payment_amount = 100, last_statement_balance = 5000 WHERE name = 'CC'")
        min_result = get_payoff_projection(conn, "minimum")
        stmt_result = get_payoff_projection(conn, "statement")
        agg_result = get_payoff_projection(conn, "aggressive")
        # Statement pays more than minimum, aggressive even more
        assert min_result[0]["monthly_payment"] < stmt_result[0]["monthly_payment"]
        assert stmt_result[0]["monthly_payment"] <= agg_result[0]["monthly_payment"]


class TestAnnualFees:
    def test_empty_db(self, conn):
        result = get_annual_fees(conn)
        assert result["accounts"] == []
        assert result["total_annual_fees"] == 0

    def test_with_fees(self, conn):
        create_account(conn, AccountCreate(
            name="Amex Gold", account_class="liability", liability_type="credit_card",
            balance=0, annual_fee=250, annual_fee_month=3,
        ))
        create_account(conn, AccountCreate(
            name="CSP", account_class="liability", liability_type="credit_card",
            balance=0, annual_fee=95, annual_fee_month=9,
        ))
        result = get_annual_fees(conn)
        assert len(result["accounts"]) == 2
        assert result["total_annual_fees"] == 345.0
        # Check by_month: March has 250, September has 95
        assert result["by_month"][2]["total"] == 250.0  # March (index 2)
        assert result["by_month"][8]["total"] == 95.0   # September (index 8)


class TestBenefitsValue:
    def test_empty_db(self, conn):
        result = get_benefits_value(conn)
        assert result["accounts"] == []
        assert result["total_benefit_value"] == 0

    def test_with_benefits(self, conn):
        cc = create_account(conn, AccountCreate(
            name="Amex Gold", account_class="liability", liability_type="credit_card",
            balance=0, annual_fee=250, annual_fee_month=3,
        ))
        conn.execute(
            "INSERT INTO ap_card_benefits (account_id, benefit_name, benefit_type, amount, frequency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [cc["id"], "Dining Credit", "credit", 10, "monthly", "2026-01-01"],
        )
        conn.execute(
            "INSERT INTO ap_card_benefits (account_id, benefit_name, benefit_type, amount, frequency, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [cc["id"], "Uber Credit", "credit", 10, "monthly", "2026-01-01"],
        )
        result = get_benefits_value(conn)
        assert len(result["accounts"]) == 1
        # 10/mo * 12 = 120 each, 240 total
        assert result["total_benefit_value"] == 240.0
        assert result["total_annual_fees"] == 250.0
        assert result["aggregate_roi"] == 0.96


class TestBalanceTrends:
    def test_empty_history(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        trends = get_balance_trends(conn, cc["id"])
        # Should have at least the initial ledger entry from create_account
        assert len(trends) >= 1

    def test_multiple_entries(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        bulk_balance_update(conn, [{"account_id": cc["id"], "current_balance": 1200}])
        bulk_balance_update(conn, [{"account_id": cc["id"], "current_balance": 900}])
        trends = get_balance_trends(conn, cc["id"])
        assert len(trends) >= 3
        # Chronological order
        assert trends[-1]["balance"] == 900.0


class TestAggregateTrend:
    def test_empty_snapshots(self, conn):
        result = get_aggregate_debt_trend(conn)
        assert result == []

    def test_with_snapshots(self, conn):
        create_account(conn, AccountCreate(name="A", account_class="asset", asset_type="checking", balance=10000))
        create_account(conn, AccountCreate(name="CC", account_class="liability", liability_type="credit_card", balance=3000))
        generate_snapshot(conn)
        result = get_aggregate_debt_trend(conn)
        assert len(result) == 1
        assert result[0]["total_assets"] == 10000.0
        assert result[0]["total_liabilities"] == 3000.0
        assert result[0]["net_worth"] == 7000.0


class TestPaymentHistorySummary:
    def test_empty(self, conn):
        result = get_payment_history_summary(conn)
        assert result == []

    def test_with_payments(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        record_payment(conn, {"from_account_id": checking["id"], "to_account_id": cc["id"], "payment_date": "2026-03-01", "amount": 500})
        record_payment(conn, {"from_account_id": checking["id"], "to_account_id": cc["id"], "payment_date": "2026-03-15", "amount": 300})
        result = get_payment_history_summary(conn)
        assert len(result) == 1
        assert result[0]["month"] == "2026-03"
        assert result[0]["count"] == 2
        assert result[0]["total"] == 800.0


# ═══════════════════════════════════════════════════════════════════════
# Phase 5: Cross-Module Integration
# ═══════════════════════════════════════════════════════════════════════


def _insert_txn(conn, date, desc, amount, account_id, bank_name, stmt_type="credit_card", subtype="spending"):
    """Helper: insert a transaction_norm row for cross-module testing."""
    import hashlib
    fp = hashlib.sha256(f"{date}{desc}{amount}{account_id}".encode()).hexdigest()
    conn.execute(
        """INSERT INTO transactions_norm (
            transaction_date, description, amount, bank_name, account_name,
            account_id, source_file, source_row, file_hash, transaction_fingerprint,
            statement_type, transaction_subtype, merchant
        ) VALUES (?, ?, ?, ?, ?, ?, 'test.csv', 1, 'testhash', ?, ?, ?, ?)""",
        [date, desc, amount, bank_name, "Test Account",
         account_id, fp, stmt_type, subtype, desc],
    )


class TestUtilizationAlerts:
    def test_no_alerts_below_threshold(self, conn):
        create_account(conn, AccountCreate(
            name="Low CC", account_class="liability", liability_type="credit_card",
            balance=1000, credit_limit=10000,
        ))
        alerts = get_utilization_alerts(conn, threshold=30.0)
        assert len(alerts) == 0

    def test_alerts_above_threshold(self, conn):
        create_account(conn, AccountCreate(
            name="High CC", account_class="liability", liability_type="credit_card",
            balance=5000, credit_limit=10000,
        ))
        alerts = get_utilization_alerts(conn, threshold=30.0)
        assert len(alerts) == 1
        assert alerts[0]["utilization_pct"] == 50.0
        assert alerts[0]["severity"] == "warning"

    def test_critical_severity(self, conn):
        create_account(conn, AccountCreate(
            name="Maxed CC", account_class="liability", liability_type="credit_card",
            balance=9000, credit_limit=10000,
        ))
        alerts = get_utilization_alerts(conn, threshold=30.0)
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "critical"

    def test_excludes_closed_accounts(self, conn):
        cc = create_account(conn, AccountCreate(
            name="Closed CC", account_class="liability", liability_type="credit_card",
            balance=8000, credit_limit=10000,
        ))
        soft_delete_account(conn, cc["id"], "closed")
        alerts = get_utilization_alerts(conn, threshold=30.0)
        assert len(alerts) == 0


class TestSpendingVsStatement:
    def test_no_cycle(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        result = spending_vs_statement(conn, cc["id"], "2026-03")
        assert result is None

    def test_no_linked_account(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1000,
            "payment_due_date": "2026-04-15",
            "statement_open_date": "2026-02-10",
            "statement_close_date": "2026-03-10",
        })
        result = spending_vs_statement(conn, cc["id"], "2026-03")
        assert result["error"] == "Account not linked to transaction data"

    def test_with_linked_account_and_transactions(self, conn):
        cc, _ = _make_cc_and_checking(conn)
        # Link the account
        conn.execute("UPDATE nw_accounts SET linked_account_id = 'cc-4428', linked_bank_name = 'Chase' WHERE id = ?", [cc["id"]])
        create_billing_cycle(conn, {
            "account_id": cc["id"],
            "cycle_label": "2026-03",
            "statement_balance": 1000,
            "payment_due_date": "2026-04-15",
            "statement_open_date": "2026-02-10",
            "statement_close_date": "2026-03-10",
        })
        # Add some transactions
        _insert_txn(conn, "2026-02-15", "Amazon", -50.00, "cc-4428", "Chase")
        _insert_txn(conn, "2026-03-01", "Walmart", -120.00, "cc-4428", "Chase")
        _insert_txn(conn, "2026-03-05", "Target", -80.00, "cc-4428", "Chase")

        result = spending_vs_statement(conn, cc["id"], "2026-03")
        assert result["statement_balance"] == 1000.0
        assert result["transaction_total"] == 250.0  # 50+120+80
        assert result["flagged"] is True  # 75% discrepancy


class TestPaymentVerification:
    def test_no_payment(self, conn):
        result = verify_payment(conn, 99999)
        assert result["verified"] is False
        assert "not found" in result["error"].lower()

    def test_no_linked_account(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        payment = record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 500,
        })
        result = verify_payment(conn, payment["id"])
        assert result["verified"] is False
        assert "not linked" in result["error"].lower()

    def test_verified_with_match(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        conn.execute("UPDATE nw_accounts SET linked_account_id = 'chk-1234', linked_bank_name = 'Chase' WHERE id = ?", [checking["id"]])
        payment = record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 500.00,
        })
        # Insert matching bank transaction
        _insert_txn(conn, "2026-03-11", "CHASE CREDIT CARD PAYMENT", -500.00, "chk-1234", "Chase", stmt_type="bank", subtype=None)

        result = verify_payment(conn, payment["id"])
        assert result["verified"] is True
        assert result["candidates"] >= 1

    def test_no_match_different_amount(self, conn):
        cc, checking = _make_cc_and_checking(conn)
        conn.execute("UPDATE nw_accounts SET linked_account_id = 'chk-1234' WHERE id = ?", [checking["id"]])
        payment = record_payment(conn, {
            "from_account_id": checking["id"],
            "to_account_id": cc["id"],
            "payment_date": "2026-03-10",
            "amount": 500.00,
        })
        _insert_txn(conn, "2026-03-10", "Some Payment", -100.00, "chk-1234", "Chase", stmt_type="bank", subtype=None)
        result = verify_payment(conn, payment["id"])
        assert result["verified"] is False


class TestSuggestedLiabilities:
    def test_empty_transactions(self, conn):
        result = suggested_liabilities(conn)
        assert result == []

    def test_recurring_charges_suggested(self, conn):
        # Insert 4 monthly charges from the same merchant
        for i in range(4):
            _insert_txn(conn, f"2026-0{i+1}-15", "Toyota Financial", -549.75,
                        "cc-1234", "Chase")
        result = suggested_liabilities(conn, min_amount=100)
        assert len(result) >= 1
        assert any("Toyota Financial" in s["merchant"] for s in result)

    def test_excludes_existing_accounts(self, conn):
        create_account(conn, AccountCreate(
            name="Toyota Financial", account_class="liability",
            liability_type="auto_loan", balance=20000,
        ))
        for i in range(4):
            _insert_txn(conn, f"2026-0{i+1}-15", "Toyota Financial", -549.75,
                        "cc-1234", "Chase")
        result = suggested_liabilities(conn, min_amount=100)
        assert not any("Toyota Financial" in s["merchant"] for s in result)


class TestAnnualFeeXref:
    def test_no_fees(self, conn):
        result = annual_fee_cross_reference(conn)
        assert result == []

    def test_no_link(self, conn):
        create_account(conn, AccountCreate(
            name="Amex Gold", account_class="liability", liability_type="credit_card",
            balance=0, annual_fee=250, annual_fee_month=3,
        ))
        result = annual_fee_cross_reference(conn)
        assert len(result) == 1
        assert result[0]["status"] == "no_link"

    def test_with_link_no_match(self, conn):
        cc = create_account(conn, AccountCreate(
            name="Amex Gold", account_class="liability", liability_type="credit_card",
            balance=0, annual_fee=250, annual_fee_month=3,
        ))
        conn.execute("UPDATE nw_accounts SET linked_account_id = 'amex-gold' WHERE id = ?", [cc["id"]])
        result = annual_fee_cross_reference(conn)
        assert len(result) == 1
        assert result[0]["status"] == "no_match"

    def test_with_link_and_match(self, conn):
        cc = create_account(conn, AccountCreate(
            name="Amex Gold", account_class="liability", liability_type="credit_card",
            balance=0, annual_fee=250, annual_fee_month=3,
        ))
        conn.execute("UPDATE nw_accounts SET linked_account_id = 'amex-gold' WHERE id = ?", [cc["id"]])
        _insert_txn(conn, "2026-03-01", "ANNUAL MEMBERSHIP FEE", -250.00, "amex-gold", "Amex")
        result = annual_fee_cross_reference(conn)
        assert len(result) == 1
        assert result[0]["status"] == "matched"
        assert result[0]["detected_fee"] == 250.0


# ── Import Wizard (Phase 6) ──────────────────────────────────────────


class TestParseNumber:
    def test_simple_integer(self):
        assert _parse_number("100") == 100.0

    def test_currency_symbol(self):
        assert _parse_number("$1,234.56") == 1234.56

    def test_negative_parentheses(self):
        assert _parse_number("($500.00)") == -500.0

    def test_euro_symbol(self):
        assert _parse_number("\u20ac99.99") == 99.99

    def test_none_input(self):
        assert _parse_number(None) is None

    def test_empty_string(self):
        assert _parse_number("") is None

    def test_non_numeric(self):
        assert _parse_number("N/A") is None


class TestInferAccountType:
    def test_mortgage(self):
        assert infer_account_type("5390 Mortgage FlagStar") == ("liability", "mortgage")

    def test_auto_loan(self):
        assert infer_account_type("Ascent - Subaru") == ("liability", "auto_loan")

    def test_student_loan(self):
        assert infer_account_type("School-Loans-Day") == ("liability", "student_loan")

    def test_utility(self):
        assert infer_account_type("We-Energies") == ("liability", "utility")

    def test_checking(self):
        assert infer_account_type("Chase Checking", "asset") == ("asset", "checking")

    def test_savings(self):
        assert infer_account_type("SoFi Savings", "asset") == ("asset", "savings")

    def test_investment(self):
        assert infer_account_type("Day-Investment", "asset") == ("asset", "investment")

    def test_digital_wallet(self):
        assert infer_account_type("PayPal Balance", "asset") == ("asset", "digital_wallet")

    def test_default_liability(self):
        assert infer_account_type("Chase Freedom 4428") == ("liability", "credit_card")

    def test_default_asset(self):
        assert infer_account_type("My Account", "asset") == ("asset", "checking")


class TestSuggestMappings:
    def test_liability_auto_match(self):
        headers = ["Account", "Current Balance", "Statement Balance", "Due Date", "APR"]
        result = suggest_account_mappings(headers, "liability")
        assert result["account_name"] == "Account"
        assert result["current_balance"] == "Current Balance"
        assert result["statement_balance"] == "Statement Balance"
        assert result["due_date"] == "Due Date"
        assert result["interest_rate"] == "APR"

    def test_asset_auto_match(self):
        headers = ["Bank Name", "Balance", "Account Type"]
        result = suggest_account_mappings(headers, "asset")
        assert result["account_name"] == "Bank Name"
        assert result["current_balance"] == "Balance"
        assert result["account_type"] == "Account Type"

    def test_no_match_returns_none(self):
        headers = ["Column1", "Column2", "Column3"]
        result = suggest_account_mappings(headers, "liability")
        # At minimum, required fields should be None
        assert result["account_name"] is None
        assert result["current_balance"] is None

    def test_headers_not_reused(self):
        # "Balance" should only match one field, not two
        headers = ["Account", "Balance"]
        result = suggest_account_mappings(headers, "liability")
        matched_headers = [v for v in result.values() if v is not None]
        assert len(matched_headers) == len(set(matched_headers))


class TestPreviewImport:
    def test_basic_preview(self, conn):
        headers = ["Name", "Balance", "Limit"]
        rows = [
            ["Chase Freedom 4428", "$3,015.41", "$12,500"],
            ["5390 Mortgage FlagStar", "$1,317.00", ""],
        ]
        mapping = {
            "account_name": "Name",
            "current_balance": "Balance",
            "credit_limit": "Limit",
        }
        result = preview_import(rows, headers, mapping, "liability", conn)
        assert result["total"] == 2
        accts = result["accounts"]
        assert accts[0]["account_name"] == "Chase Freedom 4428"
        assert accts[0]["current_balance"] == 3015.41
        assert accts[0]["credit_limit"] == 12500.0
        assert accts[0]["inferred_type"] == "credit_card"
        assert accts[1]["inferred_type"] == "mortgage"

    def test_duplicate_detection(self, conn):
        create_account(conn, AccountCreate(
            name="Chase Freedom 4428", account_class="liability",
            liability_type="credit_card", balance=3000,
        ))
        headers = ["Name", "Balance"]
        rows = [["Chase Freedom 4428", "$3,100"]]
        mapping = {"account_name": "Name", "current_balance": "Balance"}
        result = preview_import(rows, headers, mapping, "liability", conn)
        assert result["duplicates"] == 1
        assert result["accounts"][0]["is_duplicate"] is True

    def test_skips_empty_name_rows(self, conn):
        headers = ["Name", "Balance"]
        rows = [["", "$100"], ["Amex Gold", "$500"]]
        mapping = {"account_name": "Name", "current_balance": "Balance"}
        result = preview_import(rows, headers, mapping, "liability", conn)
        assert result["total"] == 1


class TestCommitImport:
    def test_create_accounts(self, conn):
        accounts = [
            {
                "account_name": "Chase Freedom 4428",
                "current_balance": 3015.41,
                "account_class": "liability",
                "inferred_type": "credit_card",
                "credit_limit": 12500,
                "interest_rate": 24.99,
                "institution": "Chase",
            },
            {
                "account_name": "SoFi Checking",
                "current_balance": 5000,
                "account_class": "asset",
                "inferred_type": "checking",
            },
        ]
        result = commit_import(conn, accounts, "skip")
        assert result["created"] == 2
        assert result["skipped"] == 0
        all_accts = list_accounts(conn)
        names = [a["name"] for a in all_accts]
        assert "Chase Freedom 4428" in names
        assert "SoFi Checking" in names

    def test_skip_duplicates(self, conn):
        create_account(conn, AccountCreate(
            name="Chase Freedom", account_class="liability",
            liability_type="credit_card", balance=1000,
        ))
        accounts = [{"account_name": "Chase Freedom", "current_balance": 2000,
                      "account_class": "liability", "inferred_type": "credit_card"}]
        result = commit_import(conn, accounts, "skip")
        assert result["skipped"] == 1
        assert result["created"] == 0

    def test_update_duplicates(self, conn):
        acct = create_account(conn, AccountCreate(
            name="Chase Freedom", account_class="liability",
            liability_type="credit_card", balance=1000,
        ))
        accounts = [{
            "account_name": "Chase Freedom", "current_balance": 2000,
            "account_class": "liability", "inferred_type": "credit_card",
            "credit_limit": 15000,
        }]
        result = commit_import(conn, accounts, "update")
        assert result["updated"] == 1
        updated = get_account(conn, acct["id"])
        assert float(updated["balance"]) == 2000.0
        assert float(updated["credit_limit"]) == 15000.0

    def test_create_even_with_duplicate_name(self, conn):
        create_account(conn, AccountCreate(
            name="Chase Freedom", account_class="liability",
            liability_type="credit_card", balance=1000,
        ))
        accounts = [{"account_name": "Chase Freedom", "current_balance": 2000,
                      "account_class": "liability", "inferred_type": "credit_card"}]
        result = commit_import(conn, accounts, "create")
        assert result["created"] == 1

    def test_due_date_parsing(self, conn):
        accounts = [{
            "account_name": "Test Card", "current_balance": 100,
            "account_class": "liability", "inferred_type": "credit_card",
            "due_date": "15",
        }]
        result = commit_import(conn, accounts, "skip")
        assert result["created"] == 1
        all_accts = list_accounts(conn)
        test_acct = [a for a in all_accts if a["name"] == "Test Card"][0]
        assert test_acct["due_day"] == 15


class TestAccountLinking:
    """Phase 6c: Account linking for transaction tab integration."""

    def test_update_linked_account(self, conn):
        cc = create_account(conn, AccountCreate(
            name="Chase Freedom", account_class="liability",
            liability_type="credit_card", balance=3000,
        ))
        update_account(conn, cc["id"], AccountUpdate(
            linked_account_id="cc-4428",
            linked_bank_name="Chase",
        ))
        updated = get_account(conn, cc["id"])
        assert updated["linked_account_id"] == "cc-4428"
        assert updated["linked_bank_name"] == "Chase"

    def test_balance_card_data(self, conn):
        """Test that account detail returns all fields needed for balance card."""
        cc = create_account(conn, AccountCreate(
            name="Chase Freedom", account_class="liability",
            liability_type="credit_card", balance=3015.41,
            credit_limit=12500, interest_rate=24.99,
            statement_balance=2800,
        ))
        acct = get_account(conn, cc["id"])
        assert acct["name"] == "Chase Freedom"
        assert float(acct["balance"]) == 3015.41
        assert float(acct["credit_limit"]) == 12500
        assert acct["data_source"] == "manual"
        assert acct["last_verified_at"] is not None


class TestAccountTypeEdit:
    """Test changing account type (class + subtype)."""

    def test_change_liability_subtype(self, conn):
        """Change a credit_card to auto_loan."""
        cc = create_account(conn, AccountCreate(
            name="Test Card", account_class="liability",
            liability_type="credit_card", balance=1000,
        ))
        assert cc["liability_type"] == "credit_card"
        assert cc["acct_type"] == "credit_card"
        assert cc["account_code"].startswith("21")  # 2100 range

        updated = update_account(conn, cc["id"], AccountUpdate(
            liability_type="auto_loan",
        ))
        assert updated["liability_type"] == "auto_loan"
        assert updated["acct_type"] == "auto_loan"
        assert updated["account_code"].startswith("22")  # 2220 range
        assert updated["account_class"] == "liability"
        assert updated["is_asset"] is False

    def test_change_asset_subtype(self, conn):
        """Change checking to savings."""
        acct = create_account(conn, AccountCreate(
            name="My Account", account_class="asset",
            asset_type="checking", balance=5000,
        ))
        assert acct["asset_type"] == "checking"

        updated = update_account(conn, acct["id"], AccountUpdate(
            asset_type="savings",
        ))
        assert updated["asset_type"] == "savings"
        assert updated["acct_type"] == "savings"
        assert updated["account_code"].startswith("112")  # 1120 range

    def test_change_class_liability_to_asset(self, conn):
        """Change from liability to asset (reclassification)."""
        acct = create_account(conn, AccountCreate(
            name="PayPal", account_class="liability",
            liability_type="other", balance=500,
        ))
        assert acct["is_asset"] is False

        updated = update_account(conn, acct["id"], AccountUpdate(
            account_class="asset",
            asset_type="digital_wallet",
        ))
        assert updated["account_class"] == "asset"
        assert updated["asset_type"] == "digital_wallet"
        assert updated["is_asset"] is True
        assert updated["acct_type"] == "digital_wallet"
        assert updated["liability_type"] is None
        assert updated["account_code"].startswith("113")  # 1130 range

    def test_change_class_asset_to_liability(self, conn):
        """Change from asset to liability."""
        acct = create_account(conn, AccountCreate(
            name="Personal Loan", account_class="asset",
            asset_type="checking", balance=1000,
        ))
        updated = update_account(conn, acct["id"], AccountUpdate(
            account_class="liability",
            liability_type="personal_debt",
        ))
        assert updated["account_class"] == "liability"
        assert updated["liability_type"] == "personal_debt"
        assert updated["is_asset"] is False
        assert updated["asset_type"] is None


# ── Plaid Stubs (Phase 7) ────────────────────────────────────────────

from finance_etl.accounts.plaid_stubs import (
    PLAID_FIELD_MAP,
    _SUBTYPE_MAP,
    REFRESH_CADENCES,
)


class TestPlaidFieldMap:
    """Validate the Plaid → Spendly field mapping is complete and consistent."""

    def test_field_map_has_core_balance_fields(self):
        assert "accounts[].balances.current" in PLAID_FIELD_MAP
        assert "accounts[].balances.available" in PLAID_FIELD_MAP

    def test_field_map_has_credit_fields(self):
        assert "liabilities.credit[].last_statement_balance" in PLAID_FIELD_MAP
        assert "liabilities.credit[].minimum_payment_amount" in PLAID_FIELD_MAP
        assert "liabilities.credit[].next_payment_due_date" in PLAID_FIELD_MAP

    def test_field_map_has_mortgage_fields(self):
        assert "liabilities.mortgage[].origination_date" in PLAID_FIELD_MAP
        assert "liabilities.mortgage[].interest_rate.percentage" in PLAID_FIELD_MAP
        assert "liabilities.mortgage[].escrow_balance" in PLAID_FIELD_MAP
        assert "liabilities.mortgage[].loan_term" in PLAID_FIELD_MAP

    def test_field_map_has_student_fields(self):
        assert "liabilities.student[].interest_rate_percentage" in PLAID_FIELD_MAP
        assert "liabilities.student[].minimum_payment_amount" in PLAID_FIELD_MAP

    def test_field_map_has_apr_fields(self):
        assert "liabilities.credit[].aprs[].apr_percentage" in PLAID_FIELD_MAP
        assert "liabilities.credit[].aprs[].apr_type" in PLAID_FIELD_MAP

    def test_all_mapped_fields_are_strings(self):
        for k, v in PLAID_FIELD_MAP.items():
            assert isinstance(k, str), f"Key {k} is not a string"
            assert isinstance(v, str), f"Value for {k} is not a string"


class TestSubtypeMap:
    """Validate subtype mapping covers common Plaid subtypes."""

    def test_depository_types(self):
        assert _SUBTYPE_MAP["checking"] == ("asset", "checking")
        assert _SUBTYPE_MAP["savings"] == ("asset", "savings")

    def test_credit_type(self):
        assert _SUBTYPE_MAP["credit card"] == ("liability", "credit_card")

    def test_loan_types(self):
        assert _SUBTYPE_MAP["mortgage"] == ("liability", "mortgage")
        assert _SUBTYPE_MAP["auto"] == ("liability", "auto_loan")
        assert _SUBTYPE_MAP["student"] == ("liability", "student_loan")

    def test_investment_types(self):
        assert _SUBTYPE_MAP["brokerage"] == ("asset", "investment")
        assert _SUBTYPE_MAP["401k"] == ("asset", "investment")
        assert _SUBTYPE_MAP["ira"] == ("asset", "investment")
        assert _SUBTYPE_MAP["roth"] == ("asset", "investment")

    def test_all_map_to_valid_classes(self):
        for subtype, (acct_class, _) in _SUBTYPE_MAP.items():
            assert acct_class in ("asset", "liability"), f"Subtype '{subtype}' maps to invalid class '{acct_class}'"


class TestRefreshCadences:
    def test_has_expected_cadences(self):
        assert "manual" in REFRESH_CADENCES
        assert "daily" in REFRESH_CADENCES
        assert "hourly" in REFRESH_CADENCES


class TestPlaidStubEndpoints:
    """Verify stub endpoints return 501 with contract documentation."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from finance_etl.accounts import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router, prefix="/accounts")
        return TestClient(app, raise_server_exceptions=False)

    def test_link_token_returns_501(self, client):
        resp = client.post("/accounts/connect/plaid/link-token")
        assert resp.status_code == 501
        body = resp.json()["detail"]
        assert body["error"] == "not_implemented"
        assert "plaid_endpoint" in body["planned_contract"]

    def test_exchange_returns_501(self, client):
        resp = client.post("/accounts/connect/plaid/exchange")
        assert resp.status_code == 501
        body = resp.json()["detail"]
        assert body["feature"] == "Plaid Token Exchange"

    def test_refresh_returns_501(self, client):
        resp = client.post("/accounts/connect/refresh")
        assert resp.status_code == 501
        body = resp.json()["detail"]
        assert "field_mapping" in body["planned_contract"]

    def test_refresh_status_returns_501(self, client):
        resp = client.get("/accounts/connect/refresh/status")
        assert resp.status_code == 501

    def test_auto_verify_returns_501(self, client):
        resp = client.post("/accounts/connect/auto-verify")
        assert resp.status_code == 501
        body = resp.json()["detail"]
        assert "processing_steps" in body["planned_contract"]

    def test_settings_returns_501(self, client):
        resp = client.get("/accounts/connect/settings")
        assert resp.status_code == 501

    def test_institutions_returns_501(self, client):
        resp = client.get("/accounts/connect/institutions")
        assert resp.status_code == 501

    def test_disconnect_returns_501(self, client):
        resp = client.delete("/accounts/connect/institutions/test-item-id")
        assert resp.status_code == 501

    def test_callback_returns_501(self, client):
        resp = client.post("/accounts/connect/plaid/callback")
        assert resp.status_code == 501

    def test_field_map_returns_200(self, client):
        """The field-map endpoint is the only one that returns 200 (it's documentation)."""
        resp = client.get("/accounts/connect/field-map")
        assert resp.status_code == 200
        body = resp.json()
        assert "plaid_to_spendly" in body
        assert "subtype_map" in body
        assert "data_sources" in body
        assert "refresh_cadences" in body


# ── Delete & Bulk Delete ────────────────────────────────────────────────


class TestDeleteAccount:

    def _make_account(self, conn, name="Test CC", **kw):
        defaults = dict(
            account_class="liability", liability_type="credit_card",
            balance=1000, credit_limit=5000,
        )
        defaults.update(kw)
        return create_account(conn, AccountCreate(name=name, **defaults))

    def test_delete_impact_empty(self, conn):
        acct = self._make_account(conn)
        impact = get_delete_impact(conn, acct["id"])
        assert impact["account_id"] == acct["id"]
        # Only the initial balance ledger entry from create_account
        assert impact["ap_balance_ledger"] == 1
        assert impact["ap_billing_cycles"] == 0
        assert impact["ap_payments"] == 0

    def test_delete_impact_with_related(self, conn):
        acct = self._make_account(conn, name="CC with data")
        aid = acct["id"]
        # Add billing cycle
        create_billing_cycle(conn, {
            "account_id": aid, "cycle_label": "2026-03",
            "statement_balance": 500, "payment_due_date": "2026-04-15",
        })
        impact = get_delete_impact(conn, aid)
        assert impact["ap_billing_cycles"] == 1
        assert impact["ap_balance_ledger"] >= 1

    def test_hard_delete_removes_account(self, conn):
        acct = self._make_account(conn, name="To Delete")
        aid = acct["id"]
        result = hard_delete_account(conn, aid)
        assert result["account_id"] == aid
        assert get_account(conn, aid) is None

    def test_hard_delete_cascades_related(self, conn):
        acct = self._make_account(conn, name="Cascade Test")
        aid = acct["id"]
        # Add billing cycle and source tag
        create_billing_cycle(conn, {
            "account_id": aid, "cycle_label": "2026-01",
            "statement_balance": 200, "payment_due_date": "2026-02-15",
        })
        create_payment_source_tag(conn, "ct_tag", aid)
        # Now hard delete
        hard_delete_account(conn, aid)
        # Verify cascade
        assert get_account(conn, aid) is None
        rows = conn.execute(
            "SELECT COUNT(*) FROM ap_billing_cycles WHERE account_id = ?", [aid]
        ).fetchone()
        assert rows[0] == 0
        rows = conn.execute(
            "SELECT COUNT(*) FROM ap_balance_ledger WHERE account_id = ?", [aid]
        ).fetchone()
        assert rows[0] == 0
        rows = conn.execute(
            "SELECT COUNT(*) FROM ap_payment_source_tags WHERE account_id = ?", [aid]
        ).fetchone()
        assert rows[0] == 0

    def test_bulk_delete_soft(self, conn):
        a1 = self._make_account(conn, name="Bulk A")
        a2 = self._make_account(conn, name="Bulk B")
        result = bulk_delete_accounts(conn, [a1["id"], a2["id"]], permanent=False)
        assert result["total"] == 2
        assert all(r["status"] == "closed" for r in result["results"])
        assert get_account(conn, a1["id"])["status"] == "closed"
        assert get_account(conn, a2["id"])["status"] == "closed"

    def test_bulk_delete_permanent(self, conn):
        a1 = self._make_account(conn, name="Perm A")
        a2 = self._make_account(conn, name="Perm B")
        result = bulk_delete_accounts(conn, [a1["id"], a2["id"]], permanent=True)
        assert result["total"] == 2
        assert all(r["status"] == "deleted" for r in result["results"])
        assert get_account(conn, a1["id"]) is None
        assert get_account(conn, a2["id"]) is None

    def test_bulk_delete_nonexistent(self, conn):
        result = bulk_delete_accounts(conn, [99999], permanent=True)
        assert result["results"][0]["status"] == "not_found"

    def test_hard_delete_with_payments(self, conn):
        src = self._make_account(conn, name="Source", account_class="asset", asset_type="checking")
        dst = self._make_account(conn, name="Dest CC")
        record_payment(conn, {
            "from_account_id": src["id"], "to_account_id": dst["id"],
            "payment_date": "2026-03-01", "amount": 100,
        })
        impact = get_delete_impact(conn, dst["id"])
        assert impact["ap_payments"] == 1
        hard_delete_account(conn, dst["id"])
        assert get_account(conn, dst["id"]) is None
        rows = conn.execute(
            "SELECT COUNT(*) FROM ap_payments WHERE to_account_id = ?", [dst["id"]]
        ).fetchone()
        assert rows[0] == 0


# ── Annual Fee ──────────────────────────────────────────────────────────


class TestAnnualFee:

    def test_create_with_annual_fee(self, conn):
        acct = create_account(conn, AccountCreate(
            name="Sapphire Preferred",
            account_class="liability",
            liability_type="credit_card",
            balance=2000,
            annual_fee=95,
            annual_fee_month=3,
        ))
        assert float(acct["annual_fee"]) == 95.0
        assert acct["annual_fee_month"] == 3

    def test_edit_add_annual_fee(self, conn):
        acct = create_account(conn, AccountCreate(
            name="Freedom Flex",
            account_class="liability",
            liability_type="credit_card",
            balance=500,
        ))
        # Initially no fee
        assert acct["annual_fee"] is None or float(acct["annual_fee"] or 0) == 0

        # Add annual fee
        result = update_account(conn, acct["id"], AccountUpdate(
            annual_fee=95,
            annual_fee_month=6,
        ))
        assert float(result["annual_fee"]) == 95.0
        assert result["annual_fee_month"] == 6

    def test_edit_remove_annual_fee(self, conn):
        acct = create_account(conn, AccountCreate(
            name="Gold Card",
            account_class="liability",
            liability_type="credit_card",
            balance=1000,
            annual_fee=250,
            annual_fee_month=10,
        ))
        assert float(acct["annual_fee"]) == 250.0

        # Remove fee by setting to 0
        result = update_account(conn, acct["id"], AccountUpdate(
            annual_fee=0,
        ))
        assert float(result["annual_fee"]) == 0
        # annual_fee_month should also be cleared
        assert result["annual_fee_month"] is None

    def test_edit_change_annual_fee_month(self, conn):
        acct = create_account(conn, AccountCreate(
            name="Platinum",
            account_class="liability",
            liability_type="credit_card",
            balance=3000,
            annual_fee=695,
            annual_fee_month=1,
        ))
        # Change only the month
        result = update_account(conn, acct["id"], AccountUpdate(
            annual_fee_month=7,
        ))
        assert float(result["annual_fee"]) == 695.0
        assert result["annual_fee_month"] == 7
