"""JWT authentication — token issuance and request-level validation.

Users are defined in AUTH_USERS_JSON env var (bcrypt-hashed passwords).
All /api/v1/* routes require a valid Bearer token unless auth_enabled=False.

Generate a password hash:
    python -c "import bcrypt; print(bcrypt.hashpw(b'mypassword', bcrypt.gensalt()).decode())"
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
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

class Role(StrEnum):
    ANALYST = "analyst"
    AUDITOR = "auditor"
    OPERATOR = "operator"
    ADMIN = "admin"


class UserConfig(BaseModel):
    username: str
    password_hash: str
    role: str = "analyst"
    tenant_id: str = "default"


class CurrentUser(BaseModel):
    username: str
    role: str
    tenant_id: str = "default"
    session_id: str | None = None
    token_version: int = 1


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_store() -> Any:
    try:
        from lex_agents_admin.user_store import get_user_store
        return get_user_store()
    except ImportError:
        return None


def _load_users(settings: Settings) -> list[UserConfig]:
    store = _get_user_store()
    if store is not None:
        db_users = store.get_all_sync()
        if db_users:
            return [
                UserConfig(
                    username=u.username,
                    password_hash=u.password_hash,
                    role=u.role,
                    tenant_id=u.tenant_id,
                )
                for u in db_users if not u.disabled
            ]
    # Fall back to env var
    try:
        raw = json.loads(settings.auth_users_json.get_secret_value())
        return [UserConfig(**u) for u in raw]
    except Exception as exc:
        logger.error("auth_users_parse_failed", error=str(exc))
        return []


def _create_token(
    username: str,
    role: str,
    settings: Settings,
    *,
    tenant_id: str = "default",
    session_id: str | None = None,
    token_version: int = 1,
) -> str:
    import uuid as _uuid
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": username,
        "role": role,
        "tid": tenant_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "jti": str(_uuid.uuid4()),
        "ver": token_version,
    }
    if session_id:
        payload["sid"] = session_id
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


def _get_session_mgr() -> Any:
    try:
        from lex_agents_admin.sessions import get_session_manager
        return get_session_manager()
    except ImportError:
        return None


async def _is_jti_revoked(store: Any, jti: str) -> bool:
    """Check JTI revocation table. Returns False (not revoked) on any error."""
    db_path = getattr(store, "_db_path", None)
    if db_path is None:
        return False
    try:
        from lex_agents_shared.db import is_postgres, pg_conn
        if is_postgres():
            async with pg_conn() as conn:
                row = await conn.fetchrow(
                    "SELECT jti FROM lex_agents_app.revoked_jtis WHERE jti=$1", jti
                )
            return row is not None
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT jti FROM revoked_jtis WHERE jti=?", (jti,)
            ) as cur:
                row_raw = await cur.fetchone()
        return row_raw is not None
    except Exception:
        return False


async def revoke_jti(db_path: str, jti: str, reason: str = "") -> None:
    """Add a JTI to the revocation list."""
    from lex_agents_shared.db import is_postgres, pg_conn
    now = datetime.now(UTC)
    if is_postgres():
        async with pg_conn() as conn:
            await conn.execute(
                "INSERT INTO lex_agents_app.revoked_jtis (jti, revoked_at, reason)"
                " VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                jti, now, reason,
            )
        return
    import aiosqlite
    now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO revoked_jtis (jti, revoked_at, reason) VALUES (?,?,?)",
            (jti, now_s, reason),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validate Bearer JWT token. Raises 401 if missing, invalid, or revoked."""
    if not settings.auth_enabled:
        return CurrentUser(username="anonymous", role="analyst", tenant_id="default")

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
        tenant_id: str = payload.get("tid", "default")
        session_id: str | None = payload.get("sid")
        jti: str | None = payload.get("jti")
        token_version: int = int(payload.get("ver", 1))
        if not username:
            raise ValueError("missing sub claim")
    except JWTError as exc:
        logger.warning("auth_token_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Check session revocation if session management is active
    if session_id:
        mgr = _get_session_mgr()
        if mgr is not None and await mgr.is_revoked(session_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Check JTI revocation (high-priority per-token revocation, fail-open on DB error)
    if jti:
        try:
            store = _get_user_store()
            if store is not None and await _is_jti_revoked(store, jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("jti_check_failed", error=str(exc))  # fail-open

    # Check token_version (bulk revocation via force-relogin)
    store = _get_user_store()
    if store is not None:
        user_rec = store._cache.get(username)
        if user_rec is not None and token_version < user_rec.token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalidated — please log in again",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return CurrentUser(
        username=username, role=role, tenant_id=tenant_id,
        session_id=session_id, token_version=token_version,
    )


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
    """Validate credentials and issue a JWT (session_id embedded separately).

    Session creation is intentionally handled in the auth router so that
    the router can pass IP/user-agent and await the async operation.
    Raises 401 on failure.
    """
    users = _load_users(settings)
    user = next((u for u in users if u.username == username), None)

    if user is None or not _bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        logger.warning("auth_login_failed", username=username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    store = _get_user_store()
    token_version = 1
    if store is not None:
        rec = store._cache.get(user.username)
        if rec is not None:
            token_version = rec.token_version
    token = _create_token(
        user.username, user.role, settings,
        tenant_id=user.tenant_id,
        token_version=token_version,
    )
    logger.info("auth_login_success", username=username, role=user.role, tenant_id=user.tenant_id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )


async def issue_token_with_session(
    username: str,
    password: str,
    settings: Settings,
    *,
    ip: str = "",
    user_agent: str = "",
) -> TokenResponse:
    """Validate credentials, create a session record, and issue a JWT with session_id."""
    users = _load_users(settings)
    user = next((u for u in users if u.username == username), None)

    if user is None or not _bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        logger.warning("auth_login_failed", username=username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_id: str | None = None
    mgr = _get_session_mgr()
    if mgr is not None:
        try:
            session_id = await mgr.create(username, user.role, ip, user_agent)
        except Exception as exc:
            logger.error("session_create_failed", error=str(exc))
            # Fail closed — issuing a token with no sid would bypass revocation checks
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Session store unavailable, please retry",
            ) from exc

    store = _get_user_store()
    token_version = 1
    if store is not None:
        rec = store._cache.get(user.username)
        if rec is not None:
            token_version = rec.token_version
    token = _create_token(
        user.username, user.role, settings,
        tenant_id=user.tenant_id,
        session_id=session_id,
        token_version=token_version,
    )
    logger.info("auth_login_success", username=username, role=user.role, tenant_id=user.tenant_id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )
