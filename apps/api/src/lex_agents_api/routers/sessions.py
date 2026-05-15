"""Session management endpoints (ADR 0057)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_auth, require_role

if TYPE_CHECKING:
    from lex_agents_admin.sessions import SessionManager, SessionRow
    from lex_agents_audit.audit_trail import AuditTrailManager

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["sessions"])

_admin_only = require_role("admin")
_op_or_admin = require_role("operator", "admin")


def _get_mgr() -> SessionManager | None:
    try:
        from lex_agents_admin.sessions import get_session_manager

        return get_session_manager()
    except ImportError:
        return None


def _get_audit() -> AuditTrailManager | None:
    try:
        from lex_agents_audit.audit_trail import get_audit_trail_manager

        return get_audit_trail_manager()
    except ImportError:
        return None


class SessionOut(BaseModel):
    id: str
    username: str
    role: str
    ip_address: str
    user_agent: str
    created_at: str
    last_used_at: str
    expires_at: str
    revoked_at: str | None
    suspicious: bool


def _to_out(s: SessionRow) -> SessionOut:
    return SessionOut(
        id=s.id,
        username=s.username,
        role=s.role,
        ip_address=s.ip_address,
        user_agent=s.user_agent,
        created_at=s.created_at,
        last_used_at=s.last_used_at,
        expires_at=s.expires_at,
        revoked_at=s.revoked_at,
        suspicious=s.suspicious,
    )


# ---------------------------------------------------------------------------
# Admin: list / revoke sessions for any user
# ---------------------------------------------------------------------------


@router.get("/admin/users/{username}/sessions", response_model=list[SessionOut])
async def list_user_sessions(
    username: str,
    user: CurrentUser = Depends(_op_or_admin),
) -> list[SessionOut]:
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Session manager not available")
    sessions = await mgr.get_active(username)
    return [_to_out(s) for s in sessions]


@router.delete("/admin/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
    user: CurrentUser = Depends(_admin_only),
) -> None:
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Session manager not available")
    ok = await mgr.revoke(session_id, revoked_by=user.username)
    if not ok:
        raise HTTPException(404, "Session not found or already revoked")
    audit = _get_audit()
    if audit:
        try:
            await audit.log(
                "session.terminate",
                "session",
                user.username,
                user.role,
                reason="Admin session termination",
                target_id=session_id,
            )
        except Exception as _audit_exc:
            logger.warning("audit_write_failed", error=str(_audit_exc))


@router.delete("/admin/users/{username}/sessions", status_code=204)
async def revoke_all_user_sessions(
    username: str,
    user: CurrentUser = Depends(_admin_only),
) -> None:
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Session manager not available")
    count = await mgr.revoke_all(username, revoked_by=user.username)
    audit = _get_audit()
    if audit:
        try:
            await audit.log(
                "session.terminate_all",
                "user",
                user.username,
                user.role,
                reason="Admin revoke all sessions",
                target_id=username,
                after={"revoked_count": count},
            )
        except Exception as _audit_exc:
            logger.warning("audit_write_failed", error=str(_audit_exc))


# ---------------------------------------------------------------------------
# Self: list own sessions / revoke others
# ---------------------------------------------------------------------------


@router.get("/me/sessions", response_model=list[SessionOut])
async def list_my_sessions(
    user: CurrentUser = Depends(require_auth),
) -> list[SessionOut]:
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Session manager not available")
    sessions = await mgr.get_active(user.username)
    return [_to_out(s) for s in sessions]


@router.delete("/me/sessions/others", status_code=204)
async def revoke_other_sessions(
    request: Request,
    user: CurrentUser = Depends(require_auth),
) -> None:
    if not user.session_id:
        raise HTTPException(
            409,
            "Current token has no session id — cannot selectively revoke others",
        )
    mgr = _get_mgr()
    if mgr is None:
        raise HTTPException(503, "Session manager not available")
    count = await mgr.revoke_all(
        user.username,
        except_session_id=user.session_id,
        revoked_by=user.username,
    )
    audit = _get_audit()
    if audit:
        try:
            await audit.log(
                "session.terminate_all",
                "user",
                user.username,
                user.role,
                reason="Self-revoke other sessions",
                target_id=user.username,
                after={"revoked_count": count, "kept_session_id": user.session_id},
            )
        except Exception as _audit_exc:
            logger.warning("audit_write_failed", error=str(_audit_exc))
