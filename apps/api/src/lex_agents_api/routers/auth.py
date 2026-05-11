"""Authentication router — POST /auth/token."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form

from lex_agents_api.auth import TokenResponse, issue_token
from lex_agents_api.settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Issue a JWT access token (OAuth2 password flow compatible)."""
    return issue_token(username, password, settings)
