"""FastAPI application factory and lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from lex_agents_api.db import ConsultationStore
from lex_agents_api.exceptions import (
    LexAgentsError,
    lex_agents_exception_handler,
    unhandled_exception_handler,
)
from lex_agents_api.logging_config import configure_logging
from lex_agents_api.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from lex_agents_api.routers import auth as auth_router
from lex_agents_api.routers import consult as consult_router
from lex_agents_api.routers import export as export_router
from lex_agents_api.routers import health as health_router
from lex_agents_api.routers import rag as rag_router
from lex_agents_api.settings import get_settings
from lex_agents_api.tracing import configure_tracing

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

def _rate_key(request: Request) -> str:
    return request.headers.get("X-User-ID") or get_remote_address(request) or "unknown"


limiter = Limiter(key_func=_rate_key)

# ---------------------------------------------------------------------------
# Content-size guard
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 64 * 1024  # 64 KB


class ContentSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cl = request.headers.get("content-length")
        if cl and int(cl) > _MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body exceeds 64 KB"}},
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
_COMMERCIAL_SOURCES = ("aranzadi", "laley", "tirant")


def _validate_commercial_sources() -> None:
    """Fail startup if any commercial source is enabled without a verified license.

    Checks CONFIG_LICENSE_VERIFIED env var and the per-source enabled flags in
    settings. Raises RuntimeError so the process exits before serving traffic.
    See ADR 0029.
    """
    import os

    license_verified = os.environ.get("CONFIG_LICENSE_VERIFIED", "").lower() == "true"
    settings = get_settings()

    for source_name in _COMMERCIAL_SOURCES:
        source_cfg = getattr(settings, f"commercial_{source_name}_enabled", False)
        if source_cfg and not license_verified:
            raise RuntimeError(
                f"Commercial source '{source_name}' is enabled in config but "
                f"CONFIG_LICENSE_VERIFIED is not set to 'true'. "
                f"Verify the signed license before enabling commercial sources. "
                f"See docs/legal/comerciales-status.md and ADR 0029."
            )


async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    configure_logging(
        log_level=settings.log_level,
        enable_pii_redaction=settings.env != "dev",
    )
    configure_tracing(
        service_name=settings.otel_service_name,
        otlp_endpoint=settings.otel_exporter_otlp_endpoint,
        service_version=settings.version,
    )

    # Guard: commercial sources must not be enabled without a verified license.
    # This fails fast at startup rather than at request time. ADR 0029.
    _validate_commercial_sources()

    logger.info(
        "startup",
        env=settings.env,
        version=settings.version,
        commit_sha=settings.commit_sha,
        qdrant_url=settings.qdrant_url,
        auth_enabled=settings.auth_enabled,
    )

    store = ConsultationStore(settings.consultation_db_path)
    await store.init()

    yield

    logger.info("shutdown")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="lex-agents API",
        description="Multi-agent legal consultation platform — banking regulation EU+ES",
        version=settings.version,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url="/redoc" if settings.env != "prod" else None,
        lifespan=lifespan,
    )

    # Rate limiter state
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Middleware (Starlette applies in reverse registration order)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ContentSizeMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    # CORS — must be outermost so preflight OPTIONS gets a response
    origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
        )

    # Domain exception handlers
    app.add_exception_handler(LexAgentsError, lex_agents_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type,unused-ignore]

    # Routers
    app.include_router(auth_router.router)    # POST /auth/token — public
    app.include_router(health_router.router)  # GET /health, /version — public
    app.include_router(rag_router.router)     # /api/v1/rag/* — auth required
    app.include_router(consult_router.router) # /api/v1/consult/* — auth required
    app.include_router(export_router.router)  # /api/v1/consult/{id}/export, /feedback

    # Prometheus metrics — /metrics (no auth, internal scrape only)
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/health", "/version"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # OTel auto-instrumentation
    FastAPIInstrumentor.instrument_app(app)

    return app


app = create_app()
