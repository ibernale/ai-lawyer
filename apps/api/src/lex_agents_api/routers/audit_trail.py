"""Audit trail read/verify/export endpoints (ADR 0035).

Read access: operator | admin
Export: admin only (export action is itself meta-audited)
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/audit-trail", tags=["audit-trail"])

_op_or_admin = require_role("operator", "admin")
_admin_only = require_role("admin")


def _get_mgr() -> Any:
    try:
        from lex_agents_audit.audit_trail import get_audit_trail_manager
        return get_audit_trail_manager()
    except ImportError:
        return None


class ExportRequest(BaseModel):
    format: str = "json"  # "json" | "csv"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_audit_trail(
    actor: str | None = None,
    action_type: str | None = None,
    target_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 100,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    mgr = _get_mgr()
    if mgr is None:
        return []
    entries = await mgr.get_history(
        actor=actor,
        action_type=action_type,
        target_type=target_type,
        since=since,
        until=until,
        limit=min(limit, 1000),
    )
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp,
            "actor_user_id": e.actor_user_id,
            "actor_role": e.actor_role,
            "action_type": e.action_type,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "before_state": e.before_state,
            "after_state": e.after_state,
            "reason": e.reason,
            "correlation_id": e.correlation_id,
            "checksum_self": e.checksum_self,
        }
        for e in entries
    ]


@router.get("/verify")
async def verify_chain(
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if mgr is None:
        return {"valid": True, "total": 0, "broken_at": None, "note": "governance db not initialised"}
    result = await mgr.verify_chain()
    return {"valid": result.valid, "total": result.total, "broken_at": result.broken_at}


@router.get("/{entry_id}")
async def get_audit_entry(
    entry_id: int,
    user: Annotated[CurrentUser, Depends(_op_or_admin)] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Governance DB not available")
    entry = await mgr.get_entry(entry_id)
    if entry is None:
        raise HTTPException(404, f"Audit entry {entry_id} not found")
    return {
        "id": entry.id,
        "timestamp": entry.timestamp,
        "actor_user_id": entry.actor_user_id,
        "actor_role": entry.actor_role,
        "action_type": entry.action_type,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "before_state": entry.before_state,
        "after_state": entry.after_state,
        "reason": entry.reason,
        "correlation_id": entry.correlation_id,
        "checksum_prev": entry.checksum_prev,
        "checksum_self": entry.checksum_self,
    }


@router.post("/export")
async def export_audit_trail(
    body: ExportRequest,
    user: Annotated[CurrentUser, Depends(_admin_only)] = None,  # type: ignore[assignment]
) -> StreamingResponse:
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Governance DB not available")

    entries = await mgr.get_history(limit=10_000)

    # Meta-audit the export itself
    try:
        await mgr.log(
            "export.audit_trail", "audit_trail",
            actor=user.username,  # type: ignore[union-attr]
            actor_role=user.role,  # type: ignore[union-attr]
            reason=f"Manual export requested (format={body.format})",
            after={"format": body.format, "rows_exported": len(entries)},
        )
    except Exception as exc:
        logger.warning("export_meta_audit_failed", error=str(exc))

    if body.format == "csv":
        output = io.StringIO()
        fieldnames = [
            "id", "timestamp", "actor_user_id", "actor_role", "action_type",
            "target_type", "target_id", "reason", "before_state", "after_state",
            "correlation_id", "checksum_self",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow({
                "id": e.id, "timestamp": e.timestamp,
                "actor_user_id": e.actor_user_id, "actor_role": e.actor_role,
                "action_type": e.action_type, "target_type": e.target_type,
                "target_id": e.target_id, "reason": e.reason,
                "before_state": e.before_state, "after_state": e.after_state,
                "correlation_id": e.correlation_id, "checksum_self": e.checksum_self,
            })
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_trail.csv"},
        )

    # JSON format
    data = [
        {
            "id": e.id, "timestamp": e.timestamp,
            "actor_user_id": e.actor_user_id, "actor_role": e.actor_role,
            "action_type": e.action_type, "target_type": e.target_type,
            "target_id": e.target_id, "reason": e.reason,
            "before_state": e.before_state, "after_state": e.after_state,
            "correlation_id": e.correlation_id,
            "checksum_prev": e.checksum_prev, "checksum_self": e.checksum_self,
        }
        for e in entries
    ]
    return StreamingResponse(
        iter([json.dumps(data, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=audit_trail.json"},
    )
