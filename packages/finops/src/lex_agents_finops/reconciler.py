"""Daily cost reconciliation — compares local estimates vs Anthropic actuals (ADR 0031)."""

from __future__ import annotations

from datetime import date

import structlog

from lex_agents_finops.cost_store import CostStore, ReconciliationRow

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MATCHED_THRESHOLD_PCT = 5.0
_DRIFT_THRESHOLD_PCT = 20.0
_MIN_ACTIVITY_TRACES = 10


class Reconciler:
    """Compare sum(local_cost_estimates_hourly) vs sum(anthropic_cost_hourly) for a date.

    Thresholds:
        diff_pct <= 5%  → matched
        diff_pct <= 20% → drift (WARNING)
        diff_pct >  20% → drift_high (CRITICAL)

    No alert is raised if trace_count < MIN_ACTIVITY_TRACES (statistical noise).
    """

    def __init__(self, cost_store: CostStore) -> None:
        self._store = cost_store

    async def run_for_date(self, target_date: date) -> ReconciliationRow:
        """Run reconciliation for target_date and persist result. Returns the row."""
        totals = await self._store.get_daily_totals(target_date)
        local_usd = totals["local_usd"]
        actual_usd = totals["anthropic_usd"]
        trace_count = int(totals["trace_count"])

        if actual_usd == 0.0 and local_usd == 0.0:
            row = ReconciliationRow(
                date=target_date.isoformat(),
                local_estimate_usd=0.0,
                anthropic_actual_usd=0.0,
                diff_usd=0.0,
                diff_pct=0.0,
                status="missing_data",
                notes="No data for either source",
            )
            await self._store.upsert_reconciliation(row)
            logger.info("reconciliation_missing_data", date=target_date.isoformat())
            return row

        if trace_count < _MIN_ACTIVITY_TRACES:
            diff_usd = actual_usd - local_usd
            diff_pct = abs(diff_usd / actual_usd * 100) if actual_usd > 0 else 0.0
            row = ReconciliationRow(
                date=target_date.isoformat(),
                local_estimate_usd=local_usd,
                anthropic_actual_usd=actual_usd,
                diff_usd=diff_usd,
                diff_pct=diff_pct,
                status="low_activity",
                notes=f"Only {trace_count} traces — below MIN_ACTIVITY_TRACES threshold",
            )
            await self._store.upsert_reconciliation(row)
            logger.info(
                "reconciliation_low_activity",
                date=target_date.isoformat(),
                trace_count=trace_count,
            )
            return row

        diff_usd = actual_usd - local_usd
        diff_pct = abs(diff_usd / actual_usd * 100) if actual_usd > 0 else 0.0

        if diff_pct >= _DRIFT_THRESHOLD_PCT:
            status = "drift_high"
            notes = _drift_cause(diff_usd, diff_pct)
            logger.critical(
                "cost_reconciliation_drift_high",
                date=target_date.isoformat(),
                local_usd=round(local_usd, 4),
                actual_usd=round(actual_usd, 4),
                diff_pct=round(diff_pct, 2),
                cause=notes,
            )
        elif diff_pct > _MATCHED_THRESHOLD_PCT:
            status = "drift"
            notes = _drift_cause(diff_usd, diff_pct)
            logger.warning(
                "cost_reconciliation_drift",
                date=target_date.isoformat(),
                local_usd=round(local_usd, 4),
                actual_usd=round(actual_usd, 4),
                diff_pct=round(diff_pct, 2),
                cause=notes,
            )
        else:
            status = "matched"
            notes = ""
            logger.info(
                "cost_reconciliation_matched",
                date=target_date.isoformat(),
                local_usd=round(local_usd, 4),
                actual_usd=round(actual_usd, 4),
                diff_pct=round(diff_pct, 2),
            )

        row = ReconciliationRow(
            date=target_date.isoformat(),
            local_estimate_usd=local_usd,
            anthropic_actual_usd=actual_usd,
            diff_usd=diff_usd,
            diff_pct=diff_pct,
            status=status,
            notes=notes,
        )
        await self._store.upsert_reconciliation(row)

        # Backfill actual_cost_usd on local estimates for precision
        await self._store.backfill_actual_cost(target_date)

        return row


def _drift_cause(diff_usd: float, diff_pct: float) -> str:
    """Return a probable cause string for the drift to include in the notes field."""
    if diff_usd > 0:
        # Actual > estimated — we spent more than we tracked
        if diff_pct >= 15.0:
            return "probable: untracked_api_calls or stale_prices"
        return "probable: untracked_api_calls (calls outside orchestrator)"
    else:
        # Estimated > actual — we over-estimated
        if diff_pct >= 15.0:
            return "probable: stale_prices (prices may have dropped)"
        return "probable: stale_prices or batch_discount_not_applied"
