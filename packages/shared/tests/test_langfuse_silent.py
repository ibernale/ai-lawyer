"""Chaos tests — LangfuseObserver must never raise even when Langfuse is unreachable."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from lex_agents_shared.observability.langfuse_client import (
    LangfuseObserver,
    _ACTIVE_TRACE,
    get_observer,
)


@pytest.fixture(autouse=True)
def _reset_observer_singleton():
    import lex_agents_shared.observability.langfuse_client as _mod
    original = _mod._observer_instance
    yield
    _mod._observer_instance = original


@pytest.fixture()
def observer_no_credentials(monkeypatch: pytest.MonkeyPatch) -> LangfuseObserver:
    """Observer with no credentials → _enabled=False, all methods are no-ops."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    return LangfuseObserver()


@pytest.fixture()
def observer_bad_host(monkeypatch: pytest.MonkeyPatch) -> LangfuseObserver:
    """Observer with credentials but unreachable host."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-fake")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-fake")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:19999")  # nothing listening
    # SDK may raise on init or on use — observer must survive both
    with patch("lex_agents_shared.observability.langfuse_client._SDK_AVAILABLE", True):
        with patch("lex_agents_shared.observability.langfuse_client._LangfuseSDK") as mock_sdk:
            mock_sdk.side_effect = RuntimeError("connection refused")
            obs = LangfuseObserver()
    return obs


class TestNoCredentials:
    def test_start_trace_no_raise(self, observer_no_credentials: LangfuseObserver) -> None:
        observer_no_credentials.start_trace(
            trace_id="t-1",
            name="user_query",
            input={"query": "test"},
        )

    def test_end_trace_no_raise(self, observer_no_credentials: LangfuseObserver) -> None:
        observer_no_credentials.end_trace(output="some result")

    def test_start_span_returns_none(self, observer_no_credentials: LangfuseObserver) -> None:
        result = observer_no_credentials.start_span("rag.search", input={"q": "test"})
        assert result is None

    def test_end_span_no_raise(self, observer_no_credentials: LangfuseObserver) -> None:
        observer_no_credentials.end_span(span=None)
        observer_no_credentials.end_span(span=MagicMock())

    def test_record_generation_no_raise(self, observer_no_credentials: LangfuseObserver) -> None:
        observer_no_credentials.record_generation(
            name="llm_call",
            model="claude-sonnet-4-6",
            prompt_name="legal_qa",
            prompt_version=1,
            messages=[{"role": "user", "content": "hello"}],
            output="world",
            input_tokens=100,
            output_tokens=50,
            cached_tokens=0,
            cost_usd=0.0015,
            latency_ms=320.0,
        )

    def test_score_trace_no_raise(self, observer_no_credentials: LangfuseObserver) -> None:
        observer_no_credentials.score_trace("verification_status", value=1.0)

    def test_flush_no_raise(self, observer_no_credentials: LangfuseObserver) -> None:
        observer_no_credentials.flush()

    def test_disabled_flag(self, observer_no_credentials: LangfuseObserver) -> None:
        assert observer_no_credentials._enabled is False


class TestBadHost:
    def test_start_trace_no_raise(self, observer_bad_host: LangfuseObserver) -> None:
        observer_bad_host.start_trace(trace_id="t-2", name="user_query", input={})

    def test_record_generation_no_raise(self, observer_bad_host: LangfuseObserver) -> None:
        observer_bad_host.record_generation(
            name="llm_call",
            model="claude-opus-4-7",
            prompt_name="",
            prompt_version=0,
            messages=[],
            output="",
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            cost_usd=0.0,
            latency_ms=0.0,
        )

    def test_end_trace_no_raise(self, observer_bad_host: LangfuseObserver) -> None:
        observer_bad_host.end_trace(output="result", metadata={"cost_usd": 0.02})


class TestExceptionSwallowing:
    """Methods must swallow ANY exception — even mocked internal failures."""

    def test_all_methods_survive_broken_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-x")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-x")

        obs = LangfuseObserver()
        obs._enabled = True

        # Make every SDK call raise
        broken = MagicMock()
        broken.trace.side_effect = RuntimeError("SDK exploded")
        broken.flush.side_effect = RuntimeError("flush exploded")
        obs._client = broken

        # None of these should propagate
        obs.start_trace(trace_id="t-3", name="test", input={})
        obs.end_trace(output="x")
        obs.start_span("span")
        obs.end_span(span=None)
        obs.record_generation(
            name="g",
            model="claude-sonnet-4-6",
            prompt_name="",
            prompt_version=0,
            messages=[],
            output="",
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            cost_usd=0.0,
            latency_ms=0.0,
        )
        obs.score_trace("name", value=0.5)
        obs.flush()


class TestContextVar:
    def test_trace_not_set_before_start(self, observer_no_credentials: LangfuseObserver) -> None:
        assert _ACTIVE_TRACE.get() is None

    def test_get_observer_returns_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        obs1 = get_observer()
        obs2 = get_observer()
        assert obs1 is obs2
