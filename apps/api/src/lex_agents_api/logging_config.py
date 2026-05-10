"""Structured JSON logging configuration using structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from lex_agents_shared.pii import redact_pii


# ---------------------------------------------------------------------------
# Custom processors
# ---------------------------------------------------------------------------

def _pii_redactor(
    logger: WrappedLogger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """Redact PII from all string values in the log event."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = redact_pii(value)
    return event_dict


def _add_correlation_id(
    logger: WrappedLogger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """Inject correlation_id from context var if present."""
    from lex_agents_api.middleware import get_correlation_id  # local import to avoid cycle

    cid = get_correlation_id()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def configure_logging(log_level: str = "INFO", enable_pii_redaction: bool = True) -> None:
    """Set up structlog with JSON output, PII redaction, and correlation IDs.

    Call once at application startup (lifespan).
    """
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_id,
    ]

    if enable_pii_redaction:
        processors.append(_pii_redactor)

    processors.extend([
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ])

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Mirror stdlib root logger to structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
