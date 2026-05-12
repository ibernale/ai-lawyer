"""User feedback endpoint — POST /api/v1/feedback."""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.db import FeedbackStore
from lex_agents_api.metrics import record_user_feedback
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

_VALID_VERDICTS = {"aceptable", "dudoso", "incorrecto"}


class FeedbackRequest(BaseModel):
    trace_id: str
    verdict: Literal["aceptable", "dudoso", "incorrecto"]
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def truncate_notes(cls, v: str | None) -> str | None:
        return v[:1000] if v else None


def _get_feedback_store(settings: Settings = Depends(get_settings)) -> FeedbackStore:
    return FeedbackStore(db_path=settings.consultation_db_path)


@router.post("", status_code=201)
async def submit_feedback(
    body: FeedbackRequest,
    current_user: CurrentUser = Depends(require_auth),
    store: FeedbackStore = Depends(_get_feedback_store),
) -> dict[str, str]:
    """Record user feedback on a consultation response."""
    if not body.trace_id.strip():
        raise HTTPException(status_code=422, detail="trace_id required")

    await store.save(
        trace_id=body.trace_id,
        verdict=body.verdict,
        notes=body.notes,
    )
    record_user_feedback(body.verdict)

    logger.info(
        "feedback_submitted",
        trace_id=body.trace_id,
        verdict=body.verdict,
        user=current_user,
    )
    return {"status": "saved", "verdict": body.verdict}


@router.get("")
async def list_feedback(
    limit: int = 50,
    _user: CurrentUser = Depends(require_auth),
    store: FeedbackStore = Depends(_get_feedback_store),
) -> list[dict[str, object]]:
    """List recent feedback entries (internal use)."""
    records = await store.list_recent(limit=limit)
    return [
        {
            "id": r.id,
            "trace_id": r.trace_id,
            "verdict": r.verdict,
            "notes": r.notes,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]
