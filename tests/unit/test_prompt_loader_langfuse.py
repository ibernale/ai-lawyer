"""Unit tests for LangfusePromptLoader — Langfuse API + filesystem fallback."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lex_agents_agents.prompt_loader import (
    LangfusePromptLoader,
    PromptConfig,
    PromptLoader,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_BODY = "Eres un asistente jurídico especializado."


def _make_prompt_config(name: str = "test_prompt", version: int = 1) -> PromptConfig:
    import hashlib
    return PromptConfig(
        name=name,
        version=version,
        model="claude-opus-4-7",
        temperature=0.0,
        max_tokens=1024,
        owner="test",
        body=_SAMPLE_BODY,
        content_hash=hashlib.sha256(_SAMPLE_BODY.encode()).hexdigest(),
    )


def _make_base_loader(name: str = "sintesis") -> PromptLoader:
    """Return a real PromptLoader that can load the 'sintesis' prompt from docs/."""
    return PromptLoader()


# ---------------------------------------------------------------------------
# Filesystem fallback (no Langfuse)
# ---------------------------------------------------------------------------


class TestFilesystemFallback:
    def test_loads_real_prompt_via_filesystem(self) -> None:
        loader = LangfusePromptLoader(base_loader=PromptLoader())
        # Disable Langfuse so it hits filesystem
        loader._enabled = False
        cfg = loader.load("sintesis")
        assert cfg.name == "sintesis"
        assert len(cfg.body) > 0

    def test_fallback_called_when_langfuse_disabled(self) -> None:
        base = MagicMock(spec=PromptLoader)
        base.load.return_value = _make_prompt_config("qna")
        loader = LangfusePromptLoader(base_loader=base)
        loader._enabled = False

        cfg = loader.load("qna")
        base.load.assert_called_once_with("qna")
        assert cfg.name == "qna"

    def test_missing_prompt_raises_from_filesystem(self) -> None:
        loader = LangfusePromptLoader(base_loader=PromptLoader())
        loader._enabled = False
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent_prompt_xyz")


# ---------------------------------------------------------------------------
# Langfuse path (mocked SDK)
# ---------------------------------------------------------------------------


class TestLangfusePath:
    def _langfuse_loader_with_mock(
        self, mock_prompt_obj: MagicMock
    ) -> LangfusePromptLoader:
        """Return a loader where the Langfuse SDK is mocked to return mock_prompt_obj."""
        base = MagicMock(spec=PromptLoader)
        base.load.return_value = _make_prompt_config()
        loader = LangfusePromptLoader(base_loader=base, ttl_seconds=300)
        loader._enabled = True

        with patch(
            "lex_agents_agents.prompt_loader._LangfuseSDK"
        ) as MockSDK:
            instance = MockSDK.return_value
            instance.get_prompt.return_value = mock_prompt_obj
            loader._langfuse_client_factory = MockSDK
            # Inject mock into _fetch_from_langfuse via patching the whole method
            loader._fetch_from_langfuse = lambda name: _make_prompt_config(name, version=mock_prompt_obj.version)

        return loader

    def test_returns_langfuse_result_when_available(self) -> None:
        mock_obj = MagicMock()
        mock_obj.version = 3
        loader = self._langfuse_loader_with_mock(mock_obj)

        cfg = loader.load("my_prompt")
        assert cfg.version == 3

    def test_langfuse_result_cached_in_ttl(self) -> None:
        call_count = 0

        def fetch(name: str) -> PromptConfig:
            nonlocal call_count
            call_count += 1
            return _make_prompt_config(name)

        loader = LangfusePromptLoader(base_loader=PromptLoader(), ttl_seconds=300)
        loader._enabled = True
        loader._fetch_from_langfuse = fetch  # type: ignore[method-assign]

        loader.load("sintesis")
        loader.load("sintesis")
        loader.load("sintesis")

        assert call_count == 1  # Only first call should hit Langfuse

    def test_cache_expires_after_ttl(self) -> None:
        call_count = 0

        def fetch(name: str) -> PromptConfig:
            nonlocal call_count
            call_count += 1
            return _make_prompt_config(name)

        loader = LangfusePromptLoader(base_loader=PromptLoader(), ttl_seconds=0)
        loader._enabled = True
        loader._fetch_from_langfuse = fetch  # type: ignore[method-assign]

        loader.load("sintesis")
        time.sleep(0.01)  # 10ms — enough to exceed ttl_seconds=0
        loader.load("sintesis")

        assert call_count == 2

    def test_fallback_on_langfuse_exception(self) -> None:
        base = MagicMock(spec=PromptLoader)
        base.load.return_value = _make_prompt_config("sintesis")

        loader = LangfusePromptLoader(base_loader=base, ttl_seconds=300)
        loader._enabled = True

        def fetch_raises(name: str) -> PromptConfig:
            raise RuntimeError("connection refused")

        loader._fetch_from_langfuse = fetch_raises  # type: ignore[method-assign]

        cfg = loader.load("sintesis")
        base.load.assert_called_once_with("sintesis")
        assert cfg.name == "sintesis"

    def test_fallback_on_langfuse_timeout(self) -> None:
        """Simulates a slow Langfuse response timing out."""
        base = MagicMock(spec=PromptLoader)
        base.load.return_value = _make_prompt_config("sintesis")

        loader = LangfusePromptLoader(base_loader=base, ttl_seconds=300)
        loader._enabled = True

        def fetch_timeout(name: str) -> PromptConfig:
            raise TimeoutError("timed out after 200ms")

        loader._fetch_from_langfuse = fetch_timeout  # type: ignore[method-assign]

        cfg = loader.load("sintesis")
        assert cfg is not None
        base.load.assert_called_once()


# ---------------------------------------------------------------------------
# Disabled (no env vars)
# ---------------------------------------------------------------------------


class TestDisabledWithoutEnvVars:
    def test_disabled_when_no_public_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        loader = LangfusePromptLoader(base_loader=PromptLoader())
        assert loader._enabled is False

    def test_loads_from_filesystem_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        loader = LangfusePromptLoader(base_loader=PromptLoader())
        cfg = loader.load("sintesis")
        assert cfg.name == "sintesis"
