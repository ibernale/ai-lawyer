"""Regulation change monitoring endpoints — /api/v1/monitoring."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from lex_agents_ingest.change_monitor import ChangeEvent, ChangeEventStore, ChangeMonitor
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, Role, require_auth, require_role
from lex_agents_api.settings import get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


# ---------------------------------------------------------------------------
# Store accessor (lazy singleton, shared per process)
# ---------------------------------------------------------------------------

_store: ChangeEventStore | None = None


def _get_store() -> ChangeEventStore:
    global _store
    if _store is None:
        settings = get_settings()
        _store = ChangeEventStore(settings.monitoring_db_path)
    return _store


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ChangeEventOut(BaseModel):
    id: str
    source_id: str
    document_id: str
    title: str
    url: str | None
    detected_at: str
    change_type: str
    domain: str
    severity: str
    summary: str | None
    read: bool


class ChangesResponse(BaseModel):
    events: list[ChangeEventOut]
    total: int
    unread_count: int


class ScanResponse(BaseModel):
    n_new: int
    events: list[ChangeEventOut]


class MarkReadResponse(BaseModel):
    ok: bool


def _to_out(event: ChangeEvent) -> ChangeEventOut:
    return ChangeEventOut(
        id=event.id,
        source_id=event.source_id,
        document_id=event.document_id,
        title=event.title,
        url=event.url,
        detected_at=event.detected_at.isoformat(),
        change_type=event.change_type,
        domain=event.domain,
        severity=event.severity,
        summary=event.summary,
        read=event.read,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/changes", response_model=ChangesResponse)
async def list_changes(
    unread_only: bool = Query(False, description="Return only unread events"),
    severity: str | None = Query(None, description="Filter by severity: high|medium|low"),
    domain: str | None = Query(None, description="Filter by regulatory domain"),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    current_user: CurrentUser = Depends(require_auth),
) -> ChangesResponse:
    """Return recent regulatory change events."""
    store = _get_store()
    try:
        await store.init()
    except Exception as exc:
        logger.warning("monitoring_store_init_failed", error=str(exc))
        return ChangesResponse(events=[], total=0, unread_count=0)

    events = await store.list_events(
        limit=limit,
        unread_only=unread_only,
        severity=severity,  # type: ignore[arg-type]
        domain=domain,
    )
    unread = await store.unread_count()

    return ChangesResponse(
        events=[_to_out(e) for e in events],
        total=len(events),
        unread_count=unread,
    )


@router.patch("/changes/{event_id}/read", response_model=MarkReadResponse)
async def mark_change_read(
    event_id: str,
    current_user: CurrentUser = Depends(require_auth),
) -> MarkReadResponse:
    """Mark a change event as read."""
    store = _get_store()
    await store.init()
    found = await store.mark_read(event_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Event {event_id!r} not found")
    return MarkReadResponse(ok=True)


_op_or_admin = require_role(Role.OPERATOR, Role.ADMIN)


@router.post("/scan", response_model=ScanResponse)
async def trigger_scan(
    current_user: Annotated[CurrentUser, Depends(_op_or_admin)],
) -> ScanResponse:
    """Trigger an on-demand scan of all configured sources (operator/admin only)."""
    from lex_agents_ingest.sources.boe import BoeSource
    from lex_agents_ingest.sources.eurlex import EurlexSource

    store = _get_store()
    await store.init()

    sources = [BoeSource(), EurlexSource()]
    monitor = ChangeMonitor(sources, store)

    try:
        new_events = await monitor.scan()
    except Exception as exc:
        logger.error("monitoring_scan_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Scan failed") from exc

    logger.info("monitoring_scan_triggered", by=current_user.username, n_new=len(new_events))
    return ScanResponse(n_new=len(new_events), events=[_to_out(e) for e in new_events])
