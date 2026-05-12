"""Langfuse observer — non-blocking wrapper with ContextVar-based trace propagation.

If Langfuse is unavailable or LANGFUSE_PUBLIC_KEY is unset, all methods silently
no-op. Observability NEVER breaks the main request path (ADR 0030).
"""

from __future__ import annotations

import os
import time
from contextvars import ContextVar
from typing import Any

import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional SDK import — works even if langfuse is not installed
# ---------------------------------------------------------------------------

try:
    from langfuse import Langfuse as _LangfuseSDK
    from langfuse.model import Usage as _LFUsage

    _SDK_AVAILABLE = True
except ImportError:
    _LangfuseSDK = None  # type: ignore[assignment,misc]
    _LFUsage = None  # type: ignore[assignment,misc]
    _SDK_AVAILABLE = False

# ---------------------------------------------------------------------------
# ContextVar: holds the active StatefulTraceClient for the current async task
# ---------------------------------------------------------------------------

_ACTIVE_TRACE: ContextVar[Any | None] = ContextVar("langfuse_active_trace", default=None)
_ACTIVE_SPAN: ContextVar[Any | None] = ContextVar("langfuse_active_span", default=None)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_observer_instance: LangfuseObserver | None = None


def get_observer() -> LangfuseObserver:
    """Return the process-level LangfuseObserver singleton."""
    global _observer_instance
    if _observer_instance is None:
        _observer_instance = LangfuseObserver()
    return _observer_instance


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class LangfuseObserver:
    """Non-blocking Langfuse wrapper.

    All public methods swallow exceptions internally and log a warning.
    The caller never needs to guard against Langfuse failures.
    """

    def __init__(self) -> None:
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "http://localhost:3002")

        self._enabled = bool(pk and sk and _SDK_AVAILABLE)
        self._client: Any = None

        if self._enabled:
            try:
                self._client = _LangfuseSDK(
                    public_key=pk,
                    secret_key=sk,
                    host=host,
                    enabled=True,
                    debug=False,
                    flush_at=15,
                    flush_interval=0.5,
                )
                logger.info("langfuse_observer_ready", host=host)
            except Exception as exc:
                logger.warning("langfuse_observer_init_failed", error=str(exc))
                self._enabled = False

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    def start_trace(
        self,
        trace_id: str,
        name: str,
        input: Any,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        if not self._enabled:
            return
        try:
            trace = self._client.trace(
                id=trace_id,
                name=name,
                input=input,
                metadata=metadata or {},
                session_id=session_id,
                tags=tags or [],
            )
            _ACTIVE_TRACE.set(trace)
        except Exception as exc:
            logger.warning("langfuse_start_trace_failed", trace_id=trace_id, error=str(exc))

    def end_trace(self, output: Any, metadata: dict[str, Any] | None = None) -> None:
        if not self._enabled:
            return
        try:
            trace = _ACTIVE_TRACE.get()
            if trace is not None:
                trace.update(output=output, metadata=metadata or {})
        except Exception as exc:
            logger.warning("langfuse_end_trace_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    def start_span(
        self,
        name: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any | None:
        """Start a child span under the active trace. Returns span handle (may be None)."""
        if not self._enabled:
            return None
        try:
            trace = _ACTIVE_TRACE.get()
            if trace is None:
                return None
            span = trace.span(
                name=name,
                input=input,
                metadata=metadata or {},
                start_time=_now(),
            )
            _ACTIVE_SPAN.set(span)
            return span
        except Exception as exc:
            logger.warning("langfuse_start_span_failed", name=name, error=str(exc))
            return None

    def end_span(
        self,
        span: Any,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._enabled or span is None:
            return
        try:
            span.end(output=output, metadata=metadata or {}, end_time=_now())
        except Exception as exc:
            logger.warning("langfuse_end_span_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Generation (LLM call)
    # ------------------------------------------------------------------

    def record_generation(
        self,
        name: str,
        model: str,
        prompt_name: str,
        prompt_version: int,
        messages: list[dict[str, Any]],
        output: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
        cost_usd: float,
        latency_ms: float,
    ) -> None:
        """Record an LLM generation under the active trace."""
        if not self._enabled:
            return
        try:
            trace = _ACTIVE_TRACE.get()
            if trace is None:
                return

            usage = _LFUsage(
                input=input_tokens,
                output=output_tokens,
                unit="TOKENS",
                input_cost=None,
                output_cost=None,
                total_cost=cost_usd,
            ) if _LFUsage is not None else None

            trace.generation(
                name=name,
                model=model,
                model_parameters={"prompt_name": prompt_name, "prompt_version": prompt_version},
                input=messages,
                output=output,
                usage=usage,
                metadata={
                    "latency_ms": latency_ms,
                    "cached_tokens": cached_tokens,
                    "cost_usd": cost_usd,
                },
                start_time=_now(),
                end_time=_now(),
            )
        except Exception as exc:
            logger.warning("langfuse_record_generation_failed", name=name, error=str(exc))

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------

    def score_trace(self, name: str, value: float, comment: str = "") -> None:
        """Add a score to the active trace (e.g. verification_status=1.0)."""
        if not self._enabled:
            return
        try:
            trace = _ACTIVE_TRACE.get()
            if trace is None:
                return
            trace.score(name=name, value=value, comment=comment)
        except Exception as exc:
            logger.warning("langfuse_score_failed", name=name, error=str(exc))

    # ------------------------------------------------------------------
    # Flush (call at process shutdown or end of test)
    # ------------------------------------------------------------------

    def flush(self) -> None:
        if not self._enabled or self._client is None:
            return
        try:
            self._client.flush()
        except Exception:
            pass


def _now() -> Any:
    """Current datetime for Langfuse timestamps."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
