"""Authentication router — POST /auth/token."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Response

from lex_agents_api.auth import TokenResponse, issue_token
from lex_agents_api.settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Issue a JWT access token (OAuth2 password flow compatible).

    Also sets a lex_jwt cookie so nginx proxies (Grafana, etc.) can inject
    the JWT as X-JWT-Assertion without requiring JS access to the token.
    """
    token_response = issue_token(username, password, settings)
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
