"""Tests for Reconciler — drift detection and status classification."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from lex_agents_finops.reconciler import Reconciler
from lex_agents_finops.cost_store import CostStore, LocalCostRow, ReconciliationRow


async def _make_store_with_data(
    tmp_path,
    local_usd: float,
    anthropic_usd: float,
    trace_count: int = 15,
) -> CostStore:
    store = CostStore(str(tmp_path / "cost.db"))
    await store.init()

    if local_usd > 0:
        await store.upsert_local_estimate(
            LocalCostRow(
                timestamp="2026-05-11T06:00:00",
                agent_name="test_agent",
                model="claude-opus-4-7",
                branch="test",
                operation_type="consultation",
                estimated_cost_usd=local_usd,
                trace_count=trace_count,
                token_count=trace_count * 1000,
            )
        )

    if anthropic_usd > 0:
        await store.upsert_cost_hourly(
            [
                {
                    "timestamp": "2026-05-11T06:00:00",
                    "description": "test",
                    "cost_usd": anthropic_usd,
                    "cost_type": "tokens",
                    "workspace": "",
                }
            ]
        )
    return store


class TestStatusClassification:
    async def test_matched_at_3_pct(self, tmp_path) -> None:
        store = await _make_store_with_data(tmp_path, local_usd=1.00, anthropic_usd=1.03)
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "matched"
        assert row.diff_pct == pytest.approx(0.03 / 1.03 * 100, rel=0.1)

    async def test_drift_at_5_7_pct(self, tmp_path) -> None:
        store = await _make_store_with_data(tmp_path, local_usd=1.00, anthropic_usd=1.06)
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "drift"
        assert row.diff_pct > 5.0

    async def test_drift_high_at_25_pct(self, tmp_path) -> None:
        store = await _make_store_with_data(tmp_path, local_usd=1.00, anthropic_usd=1.25)
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "drift_high"
        assert row.diff_pct >= 20.0


class TestLowActivity:
    async def test_low_activity_below_10_traces(self, tmp_path) -> None:
        store = await _make_store_with_data(
            tmp_path, local_usd=0.50, anthropic_usd=0.60, trace_count=5
        )
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "low_activity"

    async def test_low_activity_9_traces_no_alert(self, tmp_path) -> None:
        store = await _make_store_with_data(
            tmp_path, local_usd=0.50, anthropic_usd=0.70, trace_count=9
        )
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "low_activity"

    async def test_10_traces_triggers_evaluation(self, tmp_path) -> None:
        # drift = 40%, 10 traces → should trigger drift_high (not low_activity)
        store = await _make_store_with_data(
            tmp_path, local_usd=1.00, anthropic_usd=1.40, trace_count=10
        )
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "drift_high"


class TestMissingData:
    async def test_both_zero_is_missing_data(self, tmp_path) -> None:
        store = CostStore(str(tmp_path / "cost.db"))
        await store.init()
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.status == "missing_data"


class TestPersistence:
    async def test_row_written_to_db(self, tmp_path) -> None:
        store = await _make_store_with_data(tmp_path, local_usd=1.00, anthropic_usd=1.03)
        rec = Reconciler(store)
        await rec.run_for_date(date(2026, 5, 11))
        history = await store.get_reconciliation_history(days=7)
        assert len(history) == 1
        assert history[0].date == "2026-05-11"

    async def test_diff_fields_populated(self, tmp_path) -> None:
        store = await _make_store_with_data(tmp_path, local_usd=1.00, anthropic_usd=1.06)
        rec = Reconciler(store)
        row = await rec.run_for_date(date(2026, 5, 11))
        assert row.diff_usd == pytest.approx(0.06, abs=1e-4)
        assert row.local_estimate_usd == pytest.approx(1.00, abs=1e-4)
        assert row.anthropic_actual_usd == pytest.approx(1.06, abs=1e-4)
