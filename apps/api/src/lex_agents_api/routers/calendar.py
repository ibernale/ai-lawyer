"""Regulatory calendar endpoints — /api/v1/calendar."""

from __future__ import annotations

from datetime import date
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from lex_agents_ingest.calendar_store import CalendarEvent, CalendarEventStore, CalendarSyncer
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, Role, require_auth, require_role
from lex_agents_api.settings import get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])

# ---------------------------------------------------------------------------
# Store accessor (lazy singleton)
# ---------------------------------------------------------------------------

_store: CalendarEventStore | None = None


def _get_store() -> CalendarEventStore:
    global _store
    if _store is None:
        settings = get_settings()
        _store = CalendarEventStore(settings.calendar_db_path)
    return _store


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CalendarEventOut(BaseModel):
    id: str
    title: str
    description: str | None
    event_date: str
    deadline_type: str
    source_id: str
    url: str | None
    domain: str
    jurisdiction: str
    regulation_ref: str | None


class CalendarResponse(BaseModel):
    events: list[CalendarEventOut]
    total: int


class SyncResponse(BaseModel):
    n_upserted: int


def _to_out(event: CalendarEvent) -> CalendarEventOut:
    return CalendarEventOut(
        id=event.id,
        title=event.title,
        description=event.description,
        event_date=event.event_date.isoformat(),
        deadline_type=event.deadline_type,
        source_id=event.source_id,
        url=event.url,
        domain=event.domain,
        jurisdiction=event.jurisdiction,
        regulation_ref=event.regulation_ref,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/events", response_model=CalendarResponse)
async def list_calendar_events(
    from_date: date | None = Query(None, description="Start date (inclusive) — ISO 8601"),
    to_date: date | None = Query(None, description="End date (inclusive) — ISO 8601"),
    domain: str | None = Query(None),
    jurisdiction: str | None = Query(None),
    deadline_type: str | None = Query(
        None,
        description="consultation|application|reporting|review|publication|other",
    ),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    current_user: CurrentUser = Depends(require_auth),
) -> CalendarResponse:
    """List regulatory calendar events with optional date-range and type filters."""
    store = _get_store()
    try:
        await store.init()
    except Exception as exc:
        logger.warning("calendar_store_init_failed", error=str(exc))
        return CalendarResponse(events=[], total=0)

    events = await store.list_events(
        from_date=from_date,
        to_date=to_date,
        domain=domain,
        jurisdiction=jurisdiction,
        deadline_type=deadline_type,  # type: ignore[arg-type]
        limit=limit,
    )
    return CalendarResponse(events=[_to_out(e) for e in events], total=len(events))


@router.get("/events/upcoming", response_model=CalendarResponse)
async def upcoming_events(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    current_user: CurrentUser = Depends(require_auth),
) -> CalendarResponse:
    """Return events in the next *days* days (default 30)."""
    store = _get_store()
    try:
        await store.init()
    except Exception as exc:
        logger.warning("calendar_store_init_failed", error=str(exc))
        return CalendarResponse(events=[], total=0)

    events = await store.upcoming(days=days)
    return CalendarResponse(events=[_to_out(e) for e in events], total=len(events))


_op_or_admin = require_role(Role.OPERATOR, Role.ADMIN)


@router.post("/sync", response_model=SyncResponse)
async def sync_calendar(
    current_user: Annotated[CurrentUser, Depends(_op_or_admin)],
) -> SyncResponse:
    """Trigger an on-demand EBA calendar sync (operator/admin only)."""
    store = _get_store()
    await store.init()
    syncer = CalendarSyncer(store)

    try:
        n = await syncer.sync()
    except Exception as exc:
        logger.error("calendar_sync_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Calendar sync failed") from exc

    logger.info("calendar_sync_triggered", by=current_user.username, n_upserted=n)
    return SyncResponse(n_upserted=n)
