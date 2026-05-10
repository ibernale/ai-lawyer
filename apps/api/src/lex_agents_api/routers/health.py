"""Health and version endpoints."""

from __future__ import annotations

import sys
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, Response

from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])

# ---------------------------------------------------------------------------
# Response models (inline Pydantic — no import cycle with shared.types)
# ---------------------------------------------------------------------------

from pydantic import BaseModel  # noqa: E402


class DepsStatus(BaseModel):
    qdrant: Literal["healthy", "degraded", "unavailable"]
    anthropic_api: Literal["configured", "not_configured"]


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unavailable"]
    version: str
    deps_status: DepsStatus


class VersionResponse(BaseModel):
    version: str
    commit_sha: str
    build_time: str
    python_version: str


# ---------------------------------------------------------------------------
# Dependency: lazy qdrant wrapper from app state
# ---------------------------------------------------------------------------

def _get_qdrant_status(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Check Qdrant availability. Returns health string."""
    from fastapi import Request  # noqa: PLC0415
    # The wrapper is stored in app.state; accessed via request injection in real use.
    # Here we do a lightweight URL parse to avoid circular imports.
    try:
        import httpx
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{settings.qdrant_url}/healthz")
            return "healthy" if resp.status_code == 200 else "degraded"
    except Exception:
        return "unavailable"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health_check(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Return service health including dependency status."""
    qdrant_status = _get_qdrant_status(settings)
    anthropic_status: Literal["configured", "not_configured"] = (
        "configured"
        if settings.anthropic_api_key.get_secret_value().strip()
        else "not_configured"
    )

    overall: Literal["healthy", "degraded", "unavailable"]
    if qdrant_status == "unavailable":
        overall = "unavailable"
        response.status_code = 503
    elif qdrant_status == "degraded" or anthropic_status == "not_configured":
        overall = "degraded"
    else:
        overall = "healthy"

    result = HealthResponse(
        status=overall,
        version=settings.version,
        deps_status=DepsStatus(
            qdrant=qdrant_status,  # type: ignore[arg-type]
            anthropic_api=anthropic_status,
        ),
    )
    logger.info("health_check", status=overall, qdrant=qdrant_status, anthropic=anthropic_status)
    return result


@router.get("/version", response_model=VersionResponse)
async def version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    """Return build and version metadata."""
    return VersionResponse(
        version=settings.version,
        commit_sha=settings.commit_sha,
        build_time=settings.build_time,
        python_version=sys.version,
    )
