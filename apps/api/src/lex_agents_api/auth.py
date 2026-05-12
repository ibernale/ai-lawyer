"""JWT authentication — token issuance and request-level validation.

Users are defined in AUTH_USERS_JSON env var (bcrypt-hashed passwords).
All /api/v1/* routes require a valid Bearer token unless auth_enabled=False.

Generate a password hash:
    python -c "import bcrypt; print(bcrypt.hashpw(b'mypassword', bcrypt.gensalt()).decode())"
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Any

import bcrypt as _bcrypt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Role(str, Enum):
    ANALYST = "analyst"
    AUDITOR = "auditor"
    OPERATOR = "operator"
    ADMIN = "admin"


class UserConfig(BaseModel):
    username: str
    password_hash: str
    role: str = "analyst"


class CurrentUser(BaseModel):
    username: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_users(settings: Settings) -> list[UserConfig]:
    try:
        raw = json.loads(settings.auth_users_json.get_secret_value())
        return [UserConfig(**u) for u in raw]
    except Exception as exc:
        logger.error("auth_users_parse_failed", error=str(exc))
        return []


def _create_token(username: str, role: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    encoded: str = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return encoded


def _verify_token(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(  # type: ignore[no-any-return]
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validate Bearer JWT token. Raises 401 if missing or invalid."""
    if not settings.auth_enabled:
        return CurrentUser(username="anonymous", role="analyst")

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = _verify_token(credentials.credentials, settings)
        username: str = payload.get("sub", "")
        role: str = payload.get("role", "analyst")
        if not username:
            raise ValueError("missing sub claim")
        return CurrentUser(username=username, role=role)
    except JWTError as exc:
        logger.warning("auth_token_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Role-based access control dependency
# ---------------------------------------------------------------------------

def require_role(*roles: str) -> Any:
    """FastAPI dependency factory: enforces that the authenticated user holds one of the given roles."""
    async def _check(user: CurrentUser = Depends(require_auth)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not authorised. Required: {list(roles)}",
            )
        return user
    return _check


# ---------------------------------------------------------------------------
# Token endpoint handler (called from auth router)
# ---------------------------------------------------------------------------

def issue_token(username: str, password: str, settings: Settings) -> TokenResponse:
    """Validate credentials and issue a JWT. Raises 401 on failure."""
    users = _load_users(settings)
    user = next((u for u in users if u.username == username), None)

    if user is None or not _bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        logger.warning("auth_login_failed", username=username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _create_token(user.username, user.role, settings)
    logger.info("auth_login_success", username=username, role=user.role)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )
