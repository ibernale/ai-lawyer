"""Invitation endpoints — admin invite + public accept flow (ADR 0061)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from lex_agents_api.auth import (
    CurrentUser,
    TokenResponse,
    _create_token,
    require_role,
)
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["invitations"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class InvitationOut(BaseModel):
    id: str
    tenant_id: str
    email: str
    role: str
    invited_by: str
    expires_at: str
    created_at: str
    invite_url: str | None = None
    # raw_token is only present on create response
    token: str | None = None


class CreateInvitationRequest(BaseModel):
    email: str
    role: str = "analyst"
    ttl_hours: int = 72


class AcceptInvitationRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_invitation_store(db_path: str, secret_key: str) -> Any:
    from lex_agents_admin.invitation_store import InvitationStore
    return InvitationStore(db_path=db_path, secret_key=secret_key)


@lru_cache(maxsize=1)
def _get_user_store_cached(db_path: str) -> Any:
    from lex_agents_admin.user_store import UserStore
    return UserStore(db_path=db_path)


def get_invitation_store(settings: Settings = Depends(get_settings)) -> Any:
    return _get_invitation_store(
        settings.consultation_db_path,
        settings.jwt_secret.get_secret_value(),
    )


def get_user_store(settings: Settings = Depends(get_settings)) -> Any:
    from lex_agents_admin.user_store import get_user_store as _gs
    store = _gs()
    if store is not None:
        return store
    return _get_user_store_cached(settings.consultation_db_path)


def get_audit_store(settings: Settings = Depends(get_settings)) -> Any:
    from lex_agents_admin.user_audit_store import UserAuditStore
    return UserAuditStore(db_path=settings.consultation_db_path)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Admin endpoints (require auth + admin role)
# ---------------------------------------------------------------------------


@router.post("/api/v1/admin/invitations", response_model=InvitationOut, status_code=201)
async def create_invitation(
    body: CreateInvitationRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_role("admin")),
    inv_store: Any = Depends(get_invitation_store),
    audit: Any = Depends(get_audit_store),
) -> InvitationOut:
    """Send an invitation to a new user (admin+). Token appears once in response."""
    if body.role not in ("analyst", "auditor", "operator", "admin"):
        raise HTTPException(status_code=422, detail={"code": "INVALID_ROLE",
                                                      "message": f"Invalid role: {body.role!r}"})

    invitation = await inv_store.create(
        tenant_id=current_user.tenant_id,
        email=str(body.email),
        role=body.role,
        invited_by=current_user.username,
        ttl_hours=body.ttl_hours,
    )

    invite_url = (
        f"{_base_url(request)}/auth/accept-invitation/{invitation.raw_token}"
    )

    await audit.log(
        tenant_id=current_user.tenant_id,
        actor=current_user.username,
        action="invitation.sent",
        target=invitation.id,
        ip=request.client.host if request.client else None,
        detail={"role": body.role, "ttl_hours": body.ttl_hours},
    )
    logger.info("invitation_sent", invitation_id=invitation.id,
                tenant_id=current_user.tenant_id, role=body.role)

    return InvitationOut(
        id=invitation.id,
        tenant_id=invitation.tenant_id,
        email=invitation.email,
        role=invitation.role,
        invited_by=invitation.invited_by,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invite_url=invite_url,
        token=invitation.raw_token,
    )


@router.get("/api/v1/admin/invitations", response_model=list[InvitationOut])
async def list_invitations(
    current_user: CurrentUser = Depends(require_role("admin")),
    inv_store: Any = Depends(get_invitation_store),
) -> list[InvitationOut]:
    """List pending invitations for the current tenant."""
    invitations = await inv_store.list_pending(current_user.tenant_id)
    return [
        InvitationOut(
            id=inv.id, tenant_id=inv.tenant_id, email=inv.email,
            role=inv.role, invited_by=inv.invited_by,
            expires_at=inv.expires_at, created_at=inv.created_at,
        )
        for inv in invitations
    ]


@router.delete("/api/v1/admin/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_role("admin")),
    inv_store: Any = Depends(get_invitation_store),
    audit: Any = Depends(get_audit_store),
) -> None:
    """Revoke a pending invitation."""
    ok = await inv_store.revoke(invitation_id, revoked_by=current_user.username)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "INVITATION_NOT_FOUND",
                                                      "message": "Invitation not found or already used."})
    await audit.log(
        tenant_id=current_user.tenant_id,
        actor=current_user.username,
        action="invitation.revoked",
        target=invitation_id,
        ip=request.client.host if request.client else None,
    )


# ---------------------------------------------------------------------------
# Public accept endpoint (no auth required)
# ---------------------------------------------------------------------------


@router.post("/api/v1/auth/invitations/{token}/accept", response_model=TokenResponse)
async def accept_invitation(
    token: str,
    body: AcceptInvitationRequest,
    request: Request,
    inv_store: Any = Depends(get_invitation_store),
    user_store: Any = Depends(get_user_store),
    audit: Any = Depends(get_audit_store),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Accept an invitation: set password, create account, return JWT."""
    invitation = await inv_store.get_by_token(token)
    if invitation is None:
        raise HTTPException(status_code=404, detail={"code": "INVITATION_NOT_FOUND",
                                                      "message": "Invitation not found or invalid."})

    now_s = _now_s()
    if invitation.expires_at < now_s:
        raise HTTPException(status_code=410, detail={"code": "INVITATION_EXPIRED",
                                                      "message": "Invitation has expired."})
    if invitation.accepted_at is not None:
        raise HTTPException(status_code=409, detail={"code": "INVITATION_USED",
                                                      "message": "Invitation has already been used."})
    if invitation.revoked_at is not None:
        raise HTTPException(status_code=410, detail={"code": "INVITATION_REVOKED",
                                                      "message": "Invitation has been revoked."})

    # Validate password strength (minimum 10 chars)
    if len(body.password) < 10:
        raise HTTPException(status_code=422, detail={"code": "WEAK_PASSWORD",
                                                      "message": "Password must be at least 10 characters."})

    # Create user
    password_hash = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()
    created = await user_store.create(
        username=body.username,
        password_hash=password_hash,
        role=invitation.role,
        tenant_id=invitation.tenant_id,
    )
    if not created:
        raise HTTPException(status_code=409, detail={"code": "USERNAME_TAKEN",
                                                      "message": f"Username '{body.username}' is already taken."})

    # Mark invitation accepted
    await inv_store.accept(invitation.id, username=body.username)

    # Audit log
    ip = request.client.host if request.client else None
    await audit.log(
        tenant_id=invitation.tenant_id,
        actor=body.username,
        action="invitation.accepted",
        target=invitation.id,
        ip=ip,
        detail={"role": invitation.role},
    )
    await audit.log(
        tenant_id=invitation.tenant_id,
        actor=body.username,
        action="user.created",
        target=body.username,
        ip=ip,
        detail={"role": invitation.role, "via": "invitation"},
    )

    # Issue JWT — user is logged in immediately
    jwt_token = _create_token(
        body.username, invitation.role, settings,
        tenant_id=invitation.tenant_id,
        token_version=1,
    )
    logger.info("invitation_accepted_login", username=body.username,
                tenant_id=invitation.tenant_id, role=invitation.role)
    return TokenResponse(
        access_token=jwt_token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


def _now_s() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
