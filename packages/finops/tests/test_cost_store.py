"""Tests for CostStore — SQLite 4-table schema."""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest
import pytest_asyncio

from lex_agents_finops.cost_store import CostStore, LocalCostRow, ReconciliationRow


@pytest_asyncio.fixture
async def store(tmp_path):
    db = CostStore(str(tmp_path / "cost.db"))
    await db.init()
    return db


class TestInit:
    async def test_creates_all_four_tables(self, store: CostStore) -> None:
        import aiosqlite
        async with aiosqlite.connect(store._db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cur:
                tables = {r[0] for r in await cur.fetchall()}
        assert "anthropic_usage_hourly" in tables
        assert "anthropic_cost_hourly" in tables
        assert "local_cost_estimates_hourly" in tables
        assert "cost_reconciliation_daily" in tables

    async def test_idempotent_init(self, store: CostStore) -> None:
        # Should not raise on second call
        await store.init()


class TestUpsertUsageHourly:
    async def test_inserts_bucket(self, store: CostStore) -> None:
        buckets = [
            {
                "timestamp": "2026-05-11T00:00:00",
                "model": "claude-opus-4-7",
                "service_tier": "standard",
                "context_window": "200k",
                "workspace": "",
                "uncached_input_tokens": 1000,
                "cached_input_tokens": 200,
                "cache_creation_tokens": 50,
                "output_tokens": 500,
            }
        ]
        n = await store.upsert_usage_hourly(buckets)
        assert n == 1

    async def test_upsert_idempotent(self, store: CostStore) -> None:
        buckets = [
            {
                "timestamp": "2026-05-11T00:00:00",
                "model": "claude-opus-4-7",
                "service_tier": "standard",
                "context_window": "200k",
                "workspace": "",
                "output_tokens": 500,
            }
        ]
        await store.upsert_usage_hourly(buckets)
        await store.upsert_usage_hourly(buckets)  # second upsert should not raise
        import aiosqlite
        async with aiosqlite.connect(store._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM anthropic_usage_hourly") as cur:
                count = (await cur.fetchone())[0]
        assert count == 1

    async def test_empty_list_returns_zero(self, store: CostStore) -> None:
        assert await store.upsert_usage_hourly([]) == 0


class TestUpsertCostHourly:
    async def test_inserts_cost_bucket(self, store: CostStore) -> None:
        buckets = [
            {
                "timestamp": "2026-05-11T01:00:00",
                "description": "lex-agents-dev",
                "cost_usd": 0.0425,
                "cost_type": "tokens",
                "workspace": "default",
            }
        ]
        n = await store.upsert_cost_hourly(buckets)
        assert n == 1


class TestUpsertLocalEstimate:
    async def test_accumulates_additive(self, store: CostStore) -> None:
        row = LocalCostRow(
            timestamp="2026-05-11T06:00:00",
            agent_name="specialist_bce",
            model="claude-opus-4-7",
            branch="bce",
            operation_type="consultation",
            estimated_cost_usd=0.10,
            trace_count=1,
            token_count=2000,
        )
        await store.upsert_local_estimate(row)
        await store.upsert_local_estimate(row)  # add again

        import aiosqlite
        async with aiosqlite.connect(store._db_path) as db:
            async with db.execute(
                "SELECT estimated_cost_usd, trace_count, token_count "
                "FROM local_cost_estimates_hourly"
            ) as cur:
                r = await cur.fetchone()
        assert r[0] == pytest.approx(0.20)
        assert r[1] == 2
        assert r[2] == 4000


class TestGetLocalSummary:
    async def test_groups_by_agent(self, store: CostStore) -> None:
        for agent in ["a1", "a2", "a1"]:
            await store.upsert_local_estimate(
                LocalCostRow(
                    timestamp="2026-05-11T10:00:00",
                    agent_name=agent,
                    model="claude-sonnet-4-6",
                    branch="",
                    operation_type="consultation",
                    estimated_cost_usd=1.0,
                    trace_count=1,
                    token_count=100,
                )
            )
        rows = await store.get_local_summary(
            start=datetime(2026, 5, 11),
            end=datetime(2026, 5, 12),
            group_by="agent_name",
        )
        totals = {r["key"]: r["total_usd"] for r in rows}
        assert totals["a1"] == pytest.approx(2.0)
        assert totals["a2"] == pytest.approx(1.0)

    async def test_empty_range_returns_empty(self, store: CostStore) -> None:
        rows = await store.get_local_summary(
            start=datetime(2020, 1, 1),
            end=datetime(2020, 1, 2),
        )
        assert rows == []


class TestReconciliation:
    async def test_upsert_and_retrieve(self, store: CostStore) -> None:
        row = ReconciliationRow(
            date="2026-05-11",
            local_estimate_usd=1.00,
            anthropic_actual_usd=1.06,
            diff_usd=0.06,
            diff_pct=5.66,
            status="drift",
            notes="test",
        )
        await store.upsert_reconciliation(row)
        history = await store.get_reconciliation_history(days=7)
        assert len(history) == 1
        assert history[0].date == "2026-05-11"
        assert history[0].status == "drift"

    async def test_upsert_idempotent(self, store: CostStore) -> None:
        row = ReconciliationRow(
            date="2026-05-11",
            local_estimate_usd=1.00,
            anthropic_actual_usd=1.06,
            diff_usd=0.06,
            diff_pct=5.66,
            status="drift",
            notes="first",
        )
        await store.upsert_reconciliation(row)
        row2 = ReconciliationRow(
            date="2026-05-11",
            local_estimate_usd=1.00,
            anthropic_actual_usd=1.06,
            diff_usd=0.06,
            diff_pct=5.66,
            status="matched",
            notes="updated",
        )
        await store.upsert_reconciliation(row2)
        history = await store.get_reconciliation_history(days=7)
        assert len(history) == 1
        assert history[0].status == "matched"


class TestGetDailyTotals:
    async def test_returns_zeros_for_empty_db(self, store: CostStore) -> None:
        totals = await store.get_daily_totals(date(2026, 5, 11))
        assert totals["local_usd"] == 0.0
        assert totals["anthropic_usd"] == 0.0
        assert totals["trace_count"] == 0
