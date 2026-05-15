"""Authentication router — POST /auth/token."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from slowapi.util import get_remote_address

from lex_agents_api.auth import TokenResponse, issue_token_with_session
from lex_agents_api.limiter import limiter
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_ip_key(request: Request) -> str:  # slowapi requires param named 'request'
    return get_remote_address(request) or "unknown"


@router.post("/token", response_model=TokenResponse)
@limiter.limit("10/minute", key_func=_auth_ip_key)
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Issue a JWT access token (OAuth2 password flow compatible).

    Also sets a lex_jwt cookie so nginx proxies (Grafana, etc.) can inject
    the JWT as X-JWT-Assertion without requiring JS access to the token.
    """
    from lex_agents_audit.audit_trail import get_audit_trail_manager

    ip = get_remote_address(request) or "unknown"
    ua = request.headers.get("user-agent", "")
    audit = get_audit_trail_manager()

    try:
        token_response = await issue_token_with_session(
            username, password, settings, ip=ip, user_agent=ua
        )
    except HTTPException:
        if audit:
            try:
                await audit.log(
                    "user.login.fail",
                    "user",
                    username,
                    "unauthenticated",
                    reason="Login attempt failed",
                    after={"ip": ip, "user_agent": ua},
                )
            except Exception as _audit_exc:
                logger.warning("audit_write_failed", error=str(_audit_exc))
        raise

    if audit:
        try:
            await audit.log(
                "user.login.success",
                "user",
                username,
                "unauthenticated",
                reason="Login",
                after={"ip": ip, "user_agent": ua},
            )
        except Exception:
            pass

    response.set_cookie(
        key="lex_jwt",
        value=token_response.access_token,
        max_age=token_response.expires_in,
        samesite="lax",
        secure=(settings.env != "dev"),
        httponly=True,
        path="/",
    )
    return token_response
