"""Tests for prompt_loader.py — loading, caching, hashing."""

from __future__ import annotations

import pytest
from lex_agents_agents.prompt_loader import _CACHE, PromptConfig, load_prompt


class TestLoadRouterPrompt:
    def test_loads_router_v1(self) -> None:
        cfg = load_prompt("router", version=1)
        assert isinstance(cfg, PromptConfig)
        assert cfg.name == "router"
        assert cfg.version == 1
        assert cfg.model == "claude-opus-4-7"
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 256
        assert len(cfg.body) > 50

    def test_loads_specialist_v1(self) -> None:
        cfg = load_prompt("especialistas/regulatorio_bancario_ue_es", version=1)
        assert cfg.model == "claude-opus-4-7"
        assert cfg.max_tokens == 4096

    def test_loads_verificador_v1(self) -> None:
        cfg = load_prompt("verificador", version=1)
        assert cfg.model == "claude-haiku-4-5-20251001"
        assert cfg.max_tokens == 128


class TestCacheReturnsSameObject:
    def test_second_call_returns_same_object(self) -> None:
        _CACHE.clear()
        cfg1 = load_prompt("router", version=1)
        cfg2 = load_prompt("router", version=1)
        assert cfg1 is cfg2

    def test_different_names_are_different_objects(self) -> None:
        cfg_router = load_prompt("router", version=1)
        cfg_verif = load_prompt("verificador", version=1)
        assert cfg_router is not cfg_verif


class TestMissingPromptRaises:
    def test_nonexistent_prompt_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="Prompt not found"):
            load_prompt("nonexistent/prompt", version=99)


class TestHashStable:
    def test_hash_is_hex_string(self) -> None:
        cfg = load_prompt("router", version=1)
        assert len(cfg.content_hash) == 64
        int(cfg.content_hash, 16)  # raises ValueError if not valid hex

    def test_hash_stable_across_calls(self) -> None:
        _CACHE.clear()
        cfg1 = load_prompt("verificador", version=1)
        hash1 = cfg1.content_hash
        _CACHE.clear()
        cfg2 = load_prompt("verificador", version=1)
        assert cfg2.content_hash == hash1
