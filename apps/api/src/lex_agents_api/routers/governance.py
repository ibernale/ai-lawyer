"""Governance endpoints: prompt evolution proposals, source status, memory edits.

All routes require operator or admin role.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/governance", tags=["governance"])

_op_or_admin = require_role("operator", "admin")
_admin_only = require_role("admin")


# ---------------------------------------------------------------------------
# Dependency: governance manager
# ---------------------------------------------------------------------------

def _get_mgr() -> Any:
    """Return the AuditTrailManager singleton (set in app lifespan)."""
    try:
        from lex_agents_audit.audit_trail import get_audit_trail_manager
        return get_audit_trail_manager()
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ActionRequest(BaseModel):
    reason: str


class RequestChangesRequest(BaseModel):
    comment: str


class SourceActionRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Prompt Evolution Proposals
# ---------------------------------------------------------------------------

@router.get("/proposals")
async def list_proposals(
    status: str | None = None,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    mgr = _get_mgr()
    if mgr is None:
        return []
    proposals = await mgr.list_proposals(status=status)
    return [asdict(p) for p in proposals]


@router.post("/proposals/{pr_number}/approve")
async def approve_proposal(
    pr_number: int,
    body: ActionRequest,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")

    # Merge the PR via gh CLI
    result = subprocess.run(
        ["gh", "pr", "merge", str(pr_number), "--squash", "--auto"],
        capture_output=True, text=True, timeout=30,
    )
    gh_ok = result.returncode == 0
    if not gh_ok:
        logger.warning("gh_pr_merge_failed", pr=pr_number, stderr=result.stderr)

    if mgr:
        await mgr.update_proposal_status(
            pr_number=pr_number,
            status="approved",
            decided_by=user.username,
            decision_reason=body.reason,
        )
        await mgr.log(
            "prompt_evolution_pr.approve", "prompt_evolution_pr",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=str(pr_number),
            after={"pr_number": pr_number, "gh_merge_ok": gh_ok},
        )
        # Langfuse promote stub — wire up when Fase 8.1 merges
        logger.info("langfuse_promote_stub", pr=pr_number, specialist="unknown")

    return {"status": "approved", "pr_number": pr_number, "gh_merge_ok": gh_ok}


@router.post("/proposals/{pr_number}/reject")
async def reject_proposal(
    pr_number: int,
    body: ActionRequest,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")

    result = subprocess.run(
        ["gh", "pr", "close", str(pr_number), "--comment", body.reason],
        capture_output=True, text=True, timeout=30,
    )
    gh_ok = result.returncode == 0

    if mgr:
        await mgr.update_proposal_status(
            pr_number=pr_number,
            status="rejected",
            decided_by=user.username,
            decision_reason=body.reason,
        )
        await mgr.log(
            "prompt_evolution_pr.reject", "prompt_evolution_pr",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=str(pr_number),
            after={"pr_number": pr_number, "gh_close_ok": gh_ok},
        )

    return {"status": "rejected", "pr_number": pr_number, "gh_close_ok": gh_ok}


@router.post("/proposals/{pr_number}/request-changes")
async def request_changes_proposal(
    pr_number: int,
    body: RequestChangesRequest,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if not body.comment.strip():
        raise HTTPException(422, "comment must not be empty")

    result = subprocess.run(
        ["gh", "pr", "comment", str(pr_number), "--body", body.comment],
        capture_output=True, text=True, timeout=30,
    )
    gh_ok = result.returncode == 0

    if mgr:
        await mgr.update_proposal_status(
            pr_number=pr_number,
            status="changes_requested",
            decided_by=user.username,
            decision_reason=body.comment,
        )
        await mgr.log(
            "prompt_evolution_pr.request_changes", "prompt_evolution_pr",
            actor=user.username,
            actor_role=user.role,
            reason=body.comment,
            target_id=str(pr_number),
        )

    return {"status": "changes_requested", "pr_number": pr_number, "gh_comment_ok": gh_ok}


# ---------------------------------------------------------------------------
# Source Status
# ---------------------------------------------------------------------------

@router.get("/sources")
async def list_sources(
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    mgr = _get_mgr()
    if mgr is None:
        return []
    sources = await mgr.list_sources()
    return [asdict(s) for s in sources]


@router.post("/sources/{source_id}/pause")
async def pause_source(
    source_id: str,
    body: SourceActionRequest,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")

    if mgr:
        sources = await mgr.list_sources()
        before = next((asdict(s) for s in sources if s.source_id == source_id), None)
        if before is None:
            raise HTTPException(404, f"Source '{source_id}' not found")

        await mgr.set_source_status(
            source_id,
            "paused",
            paused_by=user.username,
            paused_reason=body.reason,
        )
        await mgr.log(
            "source.pause", "source",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=source_id,
            before=before,
            after={"status": "paused"},
        )

    return {"source_id": source_id, "status": "paused"}


@router.post("/sources/{source_id}/resume")
async def resume_source(
    source_id: str,
    body: SourceActionRequest,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")

    if mgr:
        sources = await mgr.list_sources()
        before = next((asdict(s) for s in sources if s.source_id == source_id), None)
        if before is None:
            raise HTTPException(404, f"Source '{source_id}' not found")

        await mgr.set_source_status(source_id, "active")
        await mgr.log(
            "source.resume", "source",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=source_id,
            before=before,
            after={"status": "active"},
        )

    return {"source_id": source_id, "status": "active"}


# ---------------------------------------------------------------------------
# Recent Decisions
# ---------------------------------------------------------------------------

@router.get("/recent-decisions")
async def recent_decisions(
    limit: int = 50,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    mgr = _get_mgr()
    if mgr is None:
        return []
    entries = await mgr.get_history(limit=min(limit, 200))
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp,
            "actor": e.actor_user_id,
            "actor_role": e.actor_role,
            "action_type": e.action_type,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "reason": e.reason,
        }
        for e in entries
    ]
