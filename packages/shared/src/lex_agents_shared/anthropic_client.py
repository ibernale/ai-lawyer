"""Anthropic API client wrapper with retries, timeout, and circuit breaker."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from enum import Enum
from typing import Any

import anthropic
import structlog
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Langfuse tracing — optional; skipped when LANGFUSE_SECRET_KEY is not set
# ---------------------------------------------------------------------------

_lf_client: Any = None
_lf_client_init_done = False


def _get_lf() -> Any:
    """Return a lazily-initialised Langfuse client, or None if not configured."""
    global _lf_client, _lf_client_init_done
    if _lf_client_init_done:
        return _lf_client
    _lf_client_init_done = True
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import Langfuse
        _lf_client = Langfuse()
    except Exception as exc:
        logger.debug("langfuse_init_skipped", error=str(exc))
    return _lf_client


def _lf_generation_start(kwargs: dict[str, Any]) -> Any:
    """Open a Langfuse generation span; return the span handle (or None)."""
    lf = _get_lf()
    if lf is None:
        return None
    try:
        trace = lf.trace(name="anthropic")
        return trace.generation(
            name="messages_create",
            model=kwargs.get("model", "unknown"),
            input=kwargs.get("messages", []),
            model_parameters={
                k: v for k, v in kwargs.items() if k not in ("model", "messages", "system")
            },
        )
    except Exception:
        return None


def _lf_generation_end(
    gen: Any,
    result: anthropic.types.Message | None = None,
    error: BaseException | None = None,
) -> None:
    """Close a Langfuse generation span; safe no-op on any failure."""
    if gen is None:
        return
    try:
        if result is not None:
            first = result.content[0] if result.content else None
            output = first.text if first and hasattr(first, "text") else str(result.content)
            gen.end(
                output=output,
                usage={
                    "input": result.usage.input_tokens,
                    "output": result.usage.output_tokens,
                },
            )
        else:
            gen.end(level="ERROR", status_message=str(error))
        lf = _get_lf()
        if lf is not None:
            lf.flush()
    except Exception as exc:
        logger.debug("langfuse_flush_failed", error=str(exc))

# ---------------------------------------------------------------------------
# Model constants — single source of truth for all packages
# ---------------------------------------------------------------------------

MODEL_OPUS: str = "claude-opus-4-7"
MODEL_SONNET: str = "claude-sonnet-4-6"
MODEL_HAIKU: str = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

_FAILURE_THRESHOLD = 5
_RECOVERY_TIMEOUT_S = 60.0


class _CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class _CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = _FAILURE_THRESHOLD,
        recovery_timeout: float = _RECOVERY_TIMEOUT_S,
    ) -> None:
        self._state = _CircuitState.CLOSED
        self._failures = 0
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._opened_at: float | None = None

    @property
    def state(self) -> _CircuitState:
        if self._state is _CircuitState.OPEN:
            assert self._opened_at is not None
            if time.monotonic() - self._opened_at >= self._recovery_timeout:
                self._state = _CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        self._state = _CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._state = _CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning("anthropic_circuit_breaker_opened", failures=self._failures)

    def is_open(self) -> bool:
        return self.state is _CircuitState.OPEN


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------

class AnthropicClientWrapper:
    """Thin wrapper around `anthropic.Anthropic` with retry + circuit breaker.

    Usage::

        client = AnthropicClientWrapper(api_key="sk-ant-...")
        response = await client.messages_create(model=MODEL_OPUS, ...)
    """

    def __init__(
        self,
        api_key: str,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self._async_client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
        self._max_retries = max_retries
        self._circuit = _CircuitBreaker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def messages_create(self, **kwargs: Any) -> anthropic.types.Message:
        """Call `client.messages.create` with retries, circuit breaker, and Langfuse tracing."""
        if self._circuit.is_open():
            raise RuntimeError("Anthropic circuit breaker is OPEN — refusing request")

        @retry(
            retry=retry_if_exception_type(
                (anthropic.RateLimitError, anthropic.InternalServerError)
            ),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential_jitter(initial=1, max=30),
            reraise=True,
        )
        def _call() -> anthropic.types.Message:
            return self._client.messages.create(**kwargs)  # type: ignore[no-any-return]

        gen = _lf_generation_start(kwargs)
        try:
            result = _call()
            self._circuit.record_success()
        except RetryError as exc:
            self._circuit.record_failure()
            cause = exc.last_attempt.exception() if exc.last_attempt else None
            _lf_generation_end(gen, error=exc)
            raise RuntimeError("Max retries exceeded") from cause
        except Exception as exc:
            self._circuit.record_failure()
            _lf_generation_end(gen, error=exc)
            raise
        _lf_generation_end(gen, result=result)
        return result

    async def messages_stream(self, **kwargs: Any) -> AsyncIterator[str]:
        """Stream token deltas via the Anthropic streaming API.

        Plain async generator — iterate with `async for token in client.messages_stream(...)`.
        No retry on stream — fail-fast if the connection drops mid-stream.
        Circuit breaker is checked at entry; no Langfuse tracing (tokens
        arrive incrementally; caller may wrap with its own trace span).
        """
        if self._circuit.is_open():
            raise RuntimeError("Anthropic circuit breaker is OPEN — refusing request")
        try:
            async with self._async_client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
            self._circuit.record_success()
        except Exception:
            self._circuit.record_failure()
            raise

    @property
    def circuit_state(self) -> str:
        return self._circuit.state.value
