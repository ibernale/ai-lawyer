"""Audit endpoints — GET/PUT /api/v1/audit."""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lex_agents_audit.audit_store import AuditSampleRecord, AuditStore, AuditVerdict
from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.metrics import record_audit_pending, record_audit_reviewed
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


def _get_audit_store(settings: Settings = Depends(get_settings)) -> AuditStore:
    return AuditStore(db_path=settings.consultation_db_path)


class ReviewRequest(BaseModel):
    verdict: Literal["correcto", "dudoso", "incorrecto"]
    notes: str = ""


def _sample_to_dict(r: AuditSampleRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "trace_id": r.trace_id,
        "query": r.query[:200],
        "branch": r.branch,
        "depth": r.depth,
        "sampled_at": r.sampled_at.isoformat(),
        "status": r.status,
        "reviewer": r.reviewer,
        "review_notes": r.review_notes,
        "review_verdict": r.review_verdict,
    }


@router.get("")
async def list_audit_samples(
    status: str | None = None,
    limit: int = 50,
    _user: CurrentUser = Depends(require_auth),
    store: AuditStore = Depends(_get_audit_store),
) -> list[dict[str, Any]]:
    valid_statuses = {"pending", "reviewing", "reviewed"}
    typed_status = status if status in valid_statuses else None  # type: ignore[assignment]
    records = await store.list_by_status(status=typed_status, limit=limit)
    pending_count = await store.count_pending()
    record_audit_pending(pending_count)
    return [_sample_to_dict(r) for r in records]


@router.get("/{sample_id}")
async def get_audit_sample(
    sample_id: int,
    _user: CurrentUser = Depends(require_auth),
    store: AuditStore = Depends(_get_audit_store),
) -> dict[str, Any]:
    record = await store.get(sample_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Audit sample {sample_id} not found")
    # Return full response JSON for the review UI
    return {**_sample_to_dict(record), "response_json": record.response_json}


@router.put("/{sample_id}/review", status_code=200)
async def submit_audit_review(
    sample_id: int,
    body: ReviewRequest,
    current_user: CurrentUser = Depends(require_auth),
    store: AuditStore = Depends(_get_audit_store),
) -> dict[str, str]:
    ok = await store.submit_review(
        sample_id=sample_id,
        reviewer=str(current_user),
        notes=body.notes,
        verdict=body.verdict,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Audit sample {sample_id} not found")

    record_audit_reviewed(body.verdict)
    logger.info(
        "audit_review_submitted",
        sample_id=sample_id,
        verdict=body.verdict,
        reviewer=current_user,
    )
    return {"status": "reviewed", "verdict": body.verdict}
