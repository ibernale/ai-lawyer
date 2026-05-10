"""Anthropic API client wrapper with retries, timeout, and circuit breaker."""

from __future__ import annotations

import time
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
        self._max_retries = max_retries
        self._circuit = _CircuitBreaker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def messages_create(self, **kwargs: Any) -> anthropic.types.Message:
        """Call `client.messages.create` with retries and circuit breaker."""
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
            return self._client.messages.create(**kwargs)  # type: ignore[return-value]

        try:
            result = _call()
            self._circuit.record_success()
            return result
        except RetryError as exc:
            self._circuit.record_failure()
            raise exc.last_attempt.exception() from exc  # type: ignore[union-attr]
        except Exception:
            self._circuit.record_failure()
            raise

    @property
    def circuit_state(self) -> str:
        return self._circuit.state.value
