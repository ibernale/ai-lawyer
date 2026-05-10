"""HTTP middleware: correlation ID propagation."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

CORRELATION_ID_HEADER = "X-Correlation-ID"


def get_correlation_id() -> str:
    return _correlation_id_var.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Read or generate a correlation ID and attach it to request/response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        cid = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        token = _correlation_id_var.set(cid)
        structlog.contextvars.bind_contextvars(correlation_id=cid)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = cid
            return response
        finally:
            _correlation_id_var.reset(token)
            structlog.contextvars.unbind_contextvars("correlation_id")
