"""Cost tracking endpoints — /api/v1/admin/cost/* (ADR 0031).

All endpoints require role 'operator' or 'admin'.
Admin API key (ANTHROPIC_ADMIN_KEY) is NEVER exposed to callers.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role

router = APIRouter(prefix="/api/v1/admin/cost", tags=["cost"])

_operator_or_admin = require_role("operator", "admin")

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CostBreakdownItem(BaseModel):
    key: str
    usd: float
    pct: float
    traces: int


class CostSummaryResponse(BaseModel):
    period: str
    total_usd: float
    breakdown: list[CostBreakdownItem]


class TimeseriesPoint(BaseModel):
    ts: str
    value: float


class ReconciliationItem(BaseModel):
    date: str
    local_estimate_usd: float
    anthropic_actual_usd: float
    diff_usd: float
    diff_pct: float
    status: str
    notes: str


class CostTraceDetail(BaseModel):
    trace_id: str
    estimated_usd: float | None
    note: str
    hourly_context: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Simple in-memory TTL cache (5 minutes)
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300.0


def _cached(key: str, fn: Any) -> Any:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < _CACHE_TTL:
        return entry[1]
    value = fn()
    _cache[key] = (time.monotonic(), value)
    return value


# ---------------------------------------------------------------------------
# Store accessor (lazy — resolved per request from app state)
# ---------------------------------------------------------------------------

def _get_store():  # type: ignore[return]
    try:
        from lex_agents_finops.cost_store import CostStore
        import os
        db_path = os.getenv("COST_DB_PATH", "data/cost.db")
        return CostStore(db_path)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    period: str = Query(default="today", pattern="^(today|week|month|custom)$"),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    group_by: str = Query(default="agent_name", pattern="^(agent_name|model|branch|operation_type)$"),
    _user: CurrentUser = Depends(_operator_or_admin),
) -> CostSummaryResponse:
    store = _get_store()
    now = datetime.utcnow()

    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "week":
        start = now - timedelta(days=7)
        end = now
    elif period == "month":
        start = now - timedelta(days=30)
        end = now
    else:
        start = datetime.fromisoformat(start_date) if start_date else now - timedelta(days=1)
        end = datetime.fromisoformat(end_date) if end_date else now

    cache_key = f"summary:{period}:{group_by}:{start.date()}:{end.date()}"

    async def _fetch() -> CostSummaryResponse:
        if store is None:
            return CostSummaryResponse(period=period, total_usd=0.0, breakdown=[])
        rows = await store.get_local_summary(start, end, group_by=group_by)
        total = sum(r["total_usd"] for r in rows)
        breakdown = [
            CostBreakdownItem(
                key=r["key"],
                usd=round(r["total_usd"], 6),
                pct=round(r["total_usd"] / total * 100, 2) if total > 0 else 0.0,
                traces=int(r["traces"]),
            )
            for r in rows
        ]
        return CostSummaryResponse(period=period, total_usd=round(total, 6), breakdown=breakdown)

    # For async, we can't use the sync _cached helper directly — fetch directly with own TTL
    entry = _cache.get(cache_key)
    if entry and (time.monotonic() - entry[0]) < _CACHE_TTL:
        return entry[1]
    result = await _fetch()
    _cache[cache_key] = (time.monotonic(), result)
    return result


@router.get("/timeseries", response_model=list[TimeseriesPoint])
async def get_cost_timeseries(
    metric: str = Query(default="cost", pattern="^(cost|tokens|queries)$"),
    bucket: str = Query(default="1h", pattern="^(1h|1d|1w)$"),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    _user: CurrentUser = Depends(_operator_or_admin),
) -> list[TimeseriesPoint]:
    store = _get_store()
    if store is None:
        return []
    now = datetime.utcnow()
    start = datetime.fromisoformat(start_date) if start_date else now - timedelta(days=1)
    end = datetime.fromisoformat(end_date) if end_date else now

    rows = await store.get_timeseries(metric, bucket, start, end)
    return [TimeseriesPoint(ts=r["ts"], value=float(r["value"])) for r in rows]


@router.get("/reconciliation", response_model=list[ReconciliationItem])
async def get_reconciliation_history(
    days: int = Query(default=30, ge=1, le=365),
    _user: CurrentUser = Depends(_operator_or_admin),
) -> list[ReconciliationItem]:
    store = _get_store()
    if store is None:
        return []
    rows = await store.get_reconciliation_history(days)
    return [
        ReconciliationItem(
            date=r.date,
            local_estimate_usd=r.local_estimate_usd,
            anthropic_actual_usd=r.anthropic_actual_usd,
            diff_usd=r.diff_usd,
            diff_pct=r.diff_pct,
            status=r.status,
            notes=r.notes,
        )
        for r in rows
    ]


@router.get("/per-trace/{trace_id}", response_model=CostTraceDetail)
async def get_cost_per_trace(
    trace_id: str,
    _user: CurrentUser = Depends(_operator_or_admin),
) -> CostTraceDetail:
    from lex_agents_api.db import ConsultationStore
    import os

    # Primary source: consultations.db cost_estimate_usd
    consult_store = ConsultationStore(os.getenv("CONSULTATION_DB_PATH", "data/consultations.db"))
    record = await consult_store.get(trace_id)
    estimated_usd = record.cost_estimate_usd if record else None

    # Secondary: hourly context from cost.db
    store = _get_store()
    hourly_context: list[dict[str, Any]] = []
    if store:
        detail = await store.get_cost_for_trace(trace_id)
        if detail:
            hourly_context = detail.get("hourly_buckets", [])

    return CostTraceDetail(
        trace_id=trace_id,
        estimated_usd=estimated_usd,
        note="cost_estimate_usd from consultations.db; hourly_context from cost.db",
        hourly_context=hourly_context,
    )
