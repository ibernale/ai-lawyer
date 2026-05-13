"""Notification endpoints — in-app alert center (ADR-0035)."""

from __future__ import annotations

import secrets
from dataclasses import asdict
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role
from lex_agents_api.settings import get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/notifications", tags=["notifications"])

_op_or_admin = require_role("operator", "admin")


def _get_mgr() -> Any:
    try:
        from lex_agents_audit.notifications import get_notification_manager
        return get_notification_manager()
    except ImportError:
        return None


def _require_mgr() -> Any:
    """Return the manager or raise 503."""
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Notification manager not available")
    return mgr


def _verify_webhook_secret(authorization: str | None) -> None:
    """Validate the static webhook bearer secret used by Grafana/Langfuse/Dagster.

    Callers must send:  Authorization: Bearer <NOTIFICATION_WEBHOOK_SECRET>

    If the env var is not set, the endpoint is disabled (503) to avoid
    accidentally opening an unauthenticated write surface.
    """
    expected = get_settings().notification_webhook_secret
    if not expected:
        raise HTTPException(503, "Webhook ingest disabled: NOTIFICATION_WEBHOOK_SECRET not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(403, "Invalid webhook secret")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    source: str = "grafana"
    category: str = "warning"
    title: str
    body: str
    payload: Any = None
    correlation_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_notifications(
    user: Annotated[CurrentUser, Depends(_op_or_admin)],
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    mgr = _require_mgr()
    rows = await mgr.list_unread(limit) if unread_only else await mgr.list_all(limit)
    return [asdict(r) for r in rows]


@router.get("/count")
async def get_unread_count(
    user: Annotated[CurrentUser, Depends(_op_or_admin)],
) -> dict[str, int]:
    mgr = _require_mgr()
    count = await mgr.unread_count()
    return {"unread": count}


@router.put("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: int,
    user: Annotated[CurrentUser, Depends(_op_or_admin)],
) -> None:
    mgr = _require_mgr()
    await mgr.mark_read(notification_id, read_by=user.username)


@router.put("/read-all", status_code=204)
async def mark_all_read(
    user: Annotated[CurrentUser, Depends(_op_or_admin)],
) -> None:
    mgr = _require_mgr()
    await mgr.mark_all_read(read_by=user.username)


@router.post("/ingest", status_code=204)
async def ingest_notification(
    body: IngestRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Webhook entry point for Grafana, Langfuse, and Dagster alerts.

    Authentication: static bearer secret via NOTIFICATION_WEBHOOK_SECRET env var.
    Grafana/Langfuse cannot present interactive JWTs, so we use a long-lived
    shared secret instead of the user-facing JWT auth.
    """
    _verify_webhook_secret(authorization)

    valid_categories = {"critical", "warning", "info"}
    if body.category not in valid_categories:
        raise HTTPException(422, f"category must be one of {valid_categories}")
    valid_sources = {"grafana", "langfuse", "dagster", "system"}
    if body.source not in valid_sources:
        raise HTTPException(422, f"source must be one of {valid_sources}")

    mgr = _require_mgr()
    await mgr.create(
        body.source,
        body.category,
        body.title,
        body.body,
        payload=body.payload,
        correlation_id=body.correlation_id,
    )
    logger.info("notification_ingested", source=body.source, category=body.category, title=body.title)
