"""FastAPI application factory and lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from lex_agents_audit.audit_store import AuditStore
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from lex_agents_api.db import ConsultationStore, FeedbackStore
from lex_agents_api.exceptions import (
    LexAgentsError,
    lex_agents_exception_handler,
    unhandled_exception_handler,
)
from lex_agents_api.limiter import limiter
from lex_agents_api.logging_config import configure_logging
from lex_agents_api.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from lex_agents_api.routers import audit as audit_router
from lex_agents_api.routers import auth as auth_router
from lex_agents_api.routers import consult as consult_router
from lex_agents_api.routers import export as export_router
from lex_agents_api.routers import feedback as feedback_router
from lex_agents_api.routers import health as health_router
from lex_agents_api.routers import rag as rag_router
from lex_agents_api.routers.audit_trail import router as audit_trail_router
from lex_agents_api.routers.calendar import router as calendar_router
from lex_agents_api.routers.consult_stream import router as consult_stream_router
from lex_agents_api.routers.contracts import router as contracts_router
from lex_agents_api.routers.contracts_stream import router as contracts_stream_router
from lex_agents_api.routers.documents import router as documents_router
from lex_agents_api.routers.federation import router as federation_router
from lex_agents_api.routers.governance import router as governance_router
from lex_agents_api.routers.monitoring import router as monitoring_router
from lex_agents_api.routers.notifications import router as notifications_router
from lex_agents_api.routers.ops import router as ops_router
from lex_agents_api.routers.risk_matrix import router as risk_matrix_router
from lex_agents_api.routers.sessions import router as sessions_router
from lex_agents_api.routers.system import router as system_router
from lex_agents_api.settings import get_settings
from lex_agents_api.tracing import configure_tracing

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Content-size guard
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 64 * 1024  # 64 KB (JSON endpoints)


class ContentSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Document uploads are multipart — size enforced at the endpoint, not here.
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            return await call_next(request)
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

    logger.info(
        "startup",
        env=settings.env,
        version=settings.version,
        commit_sha=settings.commit_sha,
        qdrant_url=settings.qdrant_url,
        auth_enabled=settings.auth_enabled,
    )

    # Propagate DATABASE_URL so is_postgres() works across all packages.
    # Settings reads it from env; we write it back to os.environ so the
    # shared db module (which reads os.environ directly) picks it up.
    import os as _os
    if settings.database_url:
        _os.environ.setdefault("DATABASE_URL", settings.database_url)

    store = ConsultationStore(settings.consultation_db_path)
    await store.init()

    feedback_store = FeedbackStore(settings.consultation_db_path)
    await feedback_store.init()

    # Contract store (Fase 13A)
    try:
        from lex_agents_agents.contracts.store import ContractStore
        contract_store = ContractStore(settings.consultation_db_path)
        await contract_store.init()
        logger.info("contract_store_initialized", db_path=settings.consultation_db_path)
    except ImportError:
        logger.warning("lex_agents_agents_contracts_not_available")

    audit_store = AuditStore(settings.consultation_db_path)
    await audit_store.init()

    # Governance & audit trail (ADR 0035)
    try:
        from lex_agents_audit.audit_trail import AuditTrailManager, set_audit_trail_manager
        audit_trail_mgr = AuditTrailManager(settings.governance_db_path)
        await audit_trail_mgr.init()
        set_audit_trail_manager(audit_trail_mgr)
        logger.info("governance_initialized", db_path=settings.governance_db_path)
    except ImportError:
        logger.warning("lex_agents_audit_audit_trail_not_available")

    # Session management (ADR-0057)
    try:
        from lex_agents_admin.sessions import SessionManager, set_session_manager
        session_mgr = SessionManager(settings.governance_db_path)
        await session_mgr.init()
        set_session_manager(session_mgr)
        logger.info("session_manager_initialized", db_path=settings.governance_db_path)
    except ImportError:
        logger.warning("lex_agents_admin_sessions_not_available")

    # User store (admin CRUD)
    try:
        from lex_agents_admin.user_store import UserStore, set_user_store
        user_store_mgr = UserStore(settings.governance_db_path)
        await user_store_mgr.init()
        set_user_store(user_store_mgr)
        logger.info("user_store_initialized", db_path=settings.governance_db_path)
    except ImportError:
        logger.warning("lex_agents_admin_user_store_not_available")

    # Kill switches & feature flags (ADR-0032)
    ssm = None
    try:
        from lex_agents_admin.state import SystemStateManager, set_system_state_manager
        ssm = SystemStateManager(settings.governance_db_path)
        await ssm.init()
        set_system_state_manager(ssm)
    except ImportError:
        logger.warning("lex_agents_admin_state_not_available")

    # In-app notifications (ADR-0035)
    try:
        import asyncio

        from lex_agents_audit.notifications import NotificationManager, set_notification_manager
        notif_mgr = NotificationManager(settings.governance_db_path)
        await notif_mgr.init()
        set_notification_manager(notif_mgr)
        # Wire kill-switch events → notifications
        if ssm is not None:
            # Capture the running event loop at startup time (avoids the
            # deprecated asyncio.get_event_loop() inside a sync callback).
            _loop = asyncio.get_running_loop()

            def _on_ssm_event(event: str, payload: object) -> None:
                from lex_agents_audit.notifications import get_notification_manager
                nm = get_notification_manager()
                if nm is None:
                    return
                p = payload if isinstance(payload, dict) else {}
                if event == "kill_switch.engage":
                    coro = nm.create(
                        "system", "critical",
                        f"Kill switch engaged: {p.get('target', '?')}",
                        f"Engaged by {p.get('actor', '?')} — {p.get('reason', '')}",
                        payload=p,
                    )
                elif event == "kill_switch.release":
                    coro = nm.create(
                        "system", "info",
                        f"Kill switch released: {p.get('target', '?')}",
                        f"Released by {p.get('actor', '?')}",
                        payload=p,
                    )
                else:
                    return
                try:
                    asyncio.run_coroutine_threadsafe(coro, _loop)
                except Exception as exc:
                    logger.warning("notification_create_failed", error=str(exc))
            ssm.subscribe(_on_ssm_event)
    except ImportError:
        logger.warning("lex_agents_audit_notifications_not_available")

    yield

    logger.info("shutdown")

    # Gracefully close the asyncpg pool if it was opened (Aurora mode)
    try:
        from lex_agents_shared.db import close_pool

        await close_pool()
    except Exception:  # noqa: S110
        pass  # pool may not be initialised in SQLite mode


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

    # Use the module-level limiter so @limiter.limit() decorators and
    # app.state.limiter share the same storage and exception handler.
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
    app.include_router(consult_router.router)  # /api/v1/consult/* — auth required
    app.include_router(consult_stream_router)  # /api/v1/consult/stream — SSE
    app.include_router(risk_matrix_router)     # /api/v1/consult/{id}/risk-matrix/xlsx
    app.include_router(monitoring_router)      # /api/v1/monitoring/changes, /scan
    app.include_router(calendar_router)        # /api/v1/calendar/events, /upcoming, /sync
    app.include_router(documents_router)        # /api/v1/documents — per-tenant uploads
    app.include_router(export_router.router)   # /api/v1/consult/{id}/export, /feedback
    app.include_router(feedback_router.router) # /api/v1/feedback
    app.include_router(audit_router.router)    # /api/v1/audit
    app.include_router(governance_router)      # /api/v1/admin/governance/*
    app.include_router(audit_trail_router)     # /api/v1/admin/audit-trail/*
    app.include_router(system_router)          # /api/v1/admin/system/*
    app.include_router(ops_router)             # /api/v1/admin/agents, /rag, /memory, /sources
    app.include_router(notifications_router)   # /api/v1/admin/notifications/*
    app.include_router(federation_router)      # /api/v1/admin/federation/*
    app.include_router(sessions_router)        # /api/v1/admin/users/*/sessions, /me/sessions
    app.include_router(contracts_router)        # /api/v1/contracts — contract analysis
    app.include_router(contracts_stream_router) # /api/v1/contracts/analyze/stream — SSE

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
