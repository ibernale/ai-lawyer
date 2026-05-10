"""Domain exceptions and global FastAPI exception handler."""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

logger: structlog.BoundLogger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------

class LexAgentsError(Exception):
    """Base exception for all lex-agents errors."""

    http_status: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DependencyUnavailableError(LexAgentsError):
    """Raised when a required external service (Qdrant, Anthropic) is unreachable."""

    http_status = 503
    error_code = "DEPENDENCY_UNAVAILABLE"


class ValidationError(LexAgentsError):
    """Raised when input data fails domain-level validation."""

    http_status = 422
    error_code = "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Global handler
# ---------------------------------------------------------------------------

async def lex_agents_exception_handler(
    request: Request,
    exc: LexAgentsError,
) -> JSONResponse:
    logger.error(
        "request_error",
        error_code=exc.error_code,
        message=exc.message,
        path=str(request.url.path),
        status=exc.http_status,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.error_code, "message": exc.message}},
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        path=str(request.url.path),
        exc_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}},
    )
