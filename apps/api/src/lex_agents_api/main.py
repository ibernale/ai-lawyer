"""FastAPI application factory and lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from lex_agents_api.exceptions import (
    LexAgentsError,
    lex_agents_exception_handler,
    unhandled_exception_handler,
)
from lex_agents_api.logging_config import configure_logging
from lex_agents_api.middleware import CorrelationIdMiddleware
from lex_agents_api.routers import health as health_router
from lex_agents_api.routers import rag as rag_router
from lex_agents_api.settings import get_settings
from lex_agents_api.tracing import configure_tracing

logger: structlog.BoundLogger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise and tear down shared resources."""
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

    logger.info(
        "startup",
        env=settings.env,
        version=settings.version,
        commit_sha=settings.commit_sha,
        qdrant_url=settings.qdrant_url,
    )

    yield

    logger.info("shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="lex-agents API",
        description="Multi-agent legal consultation platform — banking regulation EU+ES",
        version=settings.version,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url="/redoc" if settings.env != "prod" else None,
        lifespan=lifespan,
    )

    # Middleware (outermost first)
    app.add_middleware(CorrelationIdMiddleware)

    # Exception handlers
    app.add_exception_handler(LexAgentsError, lex_agents_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

    # Routers
    app.include_router(health_router.router)
    app.include_router(rag_router.router)

    # OTel auto-instrumentation
    FastAPIInstrumentor.instrument_app(app)

    return app


app = create_app()
