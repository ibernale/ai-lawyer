"""Role-based access control for lex-agents admin API."""

from __future__ import annotations

from enum import Enum

from fastapi import Depends, HTTPException


class Role(str, Enum):
    ANALYST = "analyst"
    AUDITOR = "auditor"
    OPERATOR = "operator"
    ADMIN = "admin"


# Role hierarchy: each role implies all roles below it in this list
_HIERARCHY: list[Role] = [Role.ANALYST, Role.AUDITOR, Role.OPERATOR, Role.ADMIN]


def role_gte(user_role: str, required_role: Role) -> bool:
    """Return True if user_role is >= required_role in the hierarchy."""
    try:
        user_idx = _HIERARCHY.index(Role(user_role))
        req_idx = _HIERARCHY.index(required_role)
        return user_idx >= req_idx
    except ValueError:
        return False


def requires_role(*roles: Role):
    """FastAPI dependency factory. Accepts any of the given roles (OR logic, no hierarchy)."""
    from lex_agents_api.auth import require_auth, CurrentUser  # late import to avoid circular

    async def _check(user: CurrentUser = Depends(require_auth)) -> CurrentUser:
        if user.role not in {r.value for r in roles}:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user.role}' is not authorised. Required: {[r.value for r in roles]}",
            )
        return user

    return _check
