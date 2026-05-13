"""System state endpoints: kill switches and feature flags (ADR-0032).

All endpoints require admin role.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin/system", tags=["system"])

_admin_only = require_role("admin")
_op_or_admin = require_role("operator", "admin")


def _get_ssm() -> Any:
    try:
        from lex_agents_admin.state import get_system_state_manager
        return get_system_state_manager()
    except ImportError:
        return None


def _get_audit_mgr() -> Any:
    try:
        from lex_agents_audit.audit_trail import get_audit_trail_manager
        return get_audit_trail_manager()
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SetFlagRequest(BaseModel):
    value: Any
    reason: str


class KillSwitchRequest(BaseModel):
    engage: bool
    reason: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/state")
async def get_system_state(
    user: Annotated[CurrentUser, Depends(_op_or_admin)],
) -> dict[str, Any]:
    ssm = _get_ssm()
    if ssm is None:
        return {"flags": [], "kill_switches": []}
    state = await ssm.get_global_state()
    return {
        "flags": [asdict(f) for f in state.flags],
        "kill_switches": [asdict(k) for k in state.kill_switches],
    }


@router.put("/flags/{key}", status_code=204)
async def set_flag(
    key: str,
    body: SetFlagRequest,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> None:
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")

    ssm = _get_ssm()
    if ssm is None:
        raise HTTPException(503, "System state manager not available")

    await ssm.set_flag(key, body.value, actor=user.username, reason=body.reason)

    audit = _get_audit_mgr()
    if audit:
        await audit.log(
            "system.flag.change", "feature_flag",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=key,
            after={"key": key, "value": body.value},
        )


@router.put("/kill/{target}", status_code=204)
async def set_kill_switch(
    target: str,
    body: KillSwitchRequest,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> None:
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")

    ssm = _get_ssm()
    if ssm is None:
        raise HTTPException(503, "System state manager not available")

    audit = _get_audit_mgr()

    if body.engage:
        await ssm.engage_kill_switch(target, actor=user.username, reason=body.reason)
        action = "system.kill_switch.engage"
    else:
        await ssm.release_kill_switch(target, actor=user.username, reason=body.reason)
        action = "system.kill_switch.release"

    if audit:
        await audit.log(
            action, "kill_switch",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=target,
            after={"engaged": body.engage},
        )
