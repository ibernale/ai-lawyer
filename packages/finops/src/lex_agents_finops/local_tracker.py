"""LocalCostTracker — accumulates per-hour cost estimates and flushes to SQLite.

Hook point: AnthropicClientWrapper._record_generation() calls record() after
each successful API call. Accumulation is in-memory (asyncio.Lock per bucket);
flush() writes to local_cost_estimates_hourly.

Singleton accessors mirror the LangfuseObserver pattern so that the singleton
can be set once at app startup and read from anywhere without import cycles.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from lex_agents_finops.cost_store import CostStore, LocalCostRow

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker_instance: LocalCostTracker | None = None


def get_local_tracker() -> LocalCostTracker | None:
    """Return the process-level LocalCostTracker singleton (may be None)."""
    return _tracker_instance


def set_local_tracker(tracker: LocalCostTracker) -> None:
    """Register the process-level singleton. Call once at application startup."""
    global _tracker_instance
    _tracker_instance = tracker
    logger.info("local_cost_tracker_registered")


# ---------------------------------------------------------------------------
# In-memory accumulation bucket
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    estimated_cost_usd: float = 0.0
    trace_count: int = 0
    token_count: int = 0


# ---------------------------------------------------------------------------
# LocalCostTracker
# ---------------------------------------------------------------------------


class LocalCostTracker:
    """Accumulates LLM call costs in memory and flushes hourly to SQLite.

    Key: (hour_ts, agent_name, model, branch, operation_type)
    """

    def __init__(self, cost_store: CostStore) -> None:
        self._store = cost_store
        self._buckets: dict[tuple[str, str, str, str, str], _Bucket] = {}
        self._lock = asyncio.Lock()

    async def record(
        self,
        agent_name: str,
        model: str,
        branch: str,
        operation_type: str,
        estimated_cost_usd: float,
        input_tokens: int,
        output_tokens: int,
        trace_id: str = "",
    ) -> None:
        """Record a single LLM call. Thread-safe via asyncio.Lock."""
        hour_ts = _hour_bucket(datetime.utcnow())
        key = (hour_ts, agent_name, model, branch, operation_type)
        async with self._lock:
            if key not in self._buckets:
                self._buckets[key] = _Bucket()
            b = self._buckets[key]
            b.estimated_cost_usd += estimated_cost_usd
            b.trace_count += 1
            b.token_count += input_tokens + output_tokens

        logger.debug(
            "local_cost_recorded",
            agent=agent_name,
            model=model,
            cost_usd=round(estimated_cost_usd, 6),
            trace_id=trace_id,
        )

    async def flush(self) -> int:
        """Write all in-memory buckets to SQLite and clear them. Returns rows flushed."""
        async with self._lock:
            snapshot = dict(self._buckets)
            self._buckets.clear()

        if not snapshot:
            return 0

        flushed = 0
        for (hour_ts, agent_name, model, branch, op_type), b in snapshot.items():
            try:
                await self._store.upsert_local_estimate(
                    LocalCostRow(
                        timestamp=hour_ts,
                        agent_name=agent_name,
                        model=model,
                        branch=branch,
                        operation_type=op_type,
                        estimated_cost_usd=b.estimated_cost_usd,
                        trace_count=b.trace_count,
                        token_count=b.token_count,
                    )
                )
                flushed += 1
            except Exception as exc:
                logger.warning(
                    "local_cost_flush_failed",
                    key=(hour_ts, agent_name, model, branch, op_type),
                    error=str(exc),
                )

        logger.info("local_cost_flushed", rows=flushed)
        return flushed


def _hour_bucket(dt: datetime) -> str:
    """Truncate datetime to the start of its hour in ISO format."""
    return dt.replace(minute=0, second=0, microsecond=0).isoformat()
