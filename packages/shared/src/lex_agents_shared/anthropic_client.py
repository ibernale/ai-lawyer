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

# Langfuse and PricingCalculator imported lazily to avoid hard dependency at module load
_pricing_calculator: Any = None


def _get_pricing_calculator() -> Any:
    global _pricing_calculator
    if _pricing_calculator is None:
        try:
            from lex_agents_shared.observability.pricing_calculator import PricingCalculator
            _pricing_calculator = PricingCalculator()
        except Exception:
            pass
    return _pricing_calculator

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
        """Call `client.messages.create` with retries and circuit breaker.

        Optional Langfuse instrumentation kwargs (stripped before API call):
          _lf_prompt_name: str     — prompt identifier for Langfuse
          _lf_prompt_version: int  — prompt version for Langfuse
        """
        if self._circuit.is_open():
            raise RuntimeError("Anthropic circuit breaker is OPEN — refusing request")

        # Extract Langfuse metadata before passing to Anthropic API
        lf_prompt_name: str = kwargs.pop("_lf_prompt_name", "")
        lf_prompt_version: int = kwargs.pop("_lf_prompt_version", 0)

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

        t0 = time.monotonic()
        try:
            result = _call()
            self._circuit.record_success()
            latency_ms = (time.monotonic() - t0) * 1000
            self._record_generation(result, lf_prompt_name, lf_prompt_version, kwargs, latency_ms)
            return result
        except RetryError as exc:
            self._circuit.record_failure()
            cause = exc.last_attempt.exception() if exc.last_attempt else None
            raise RuntimeError("Max retries exceeded") from cause
        except Exception:
            self._circuit.record_failure()
            raise

    def _record_generation(
        self,
        result: anthropic.types.Message,
        prompt_name: str,
        prompt_version: int,
        call_kwargs: dict[str, Any],
        latency_ms: float,
    ) -> None:
        """Push generation metadata to Langfuse if a trace is active. Never raises."""
        try:
            from lex_agents_shared.observability.langfuse_client import get_observer
            observer = get_observer()
            if not observer._enabled:
                return

            usage = result.usage
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
            cached_tok = getattr(usage, "cache_read_input_tokens", 0) or 0

            calc = _get_pricing_calculator()
            cost_usd = 0.0
            if calc is not None:
                cost_usd = calc.estimate(
                    model=result.model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cached_tokens=cached_tok,
                )

            # Extract text content from response
            output_text = ""
            for block in result.content:
                if hasattr(block, "text"):
                    output_text = block.text
                    break

            messages: list[dict[str, Any]] = call_kwargs.get("messages", [])

            observer.record_generation(
                name=prompt_name or "llm_call",
                model=result.model,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                messages=messages,
                output=output_text,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cached_tokens=cached_tok,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("anthropic_langfuse_record_failed", error=str(exc))

    @property
    def circuit_state(self) -> str:
        return self._circuit.state.value
