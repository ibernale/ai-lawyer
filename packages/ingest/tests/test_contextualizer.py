"""Unit tests for Contextualizer — verifies prompt caching and local cache."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from lex_agents_ingest.canonical import CanonicalDocument, Chunk
from lex_agents_ingest.contextualizer import Contextualizer


def _make_doc() -> CanonicalDocument:
    return CanonicalDocument(
        source="eurlex",
        source_id="32013R0575",
        title="CRR",
        publication_date=date(2013, 6, 27),
        full_text="El presente Reglamento establece normas uniformes. " * 60,
    )


def _make_chunk(text: str, n: int = 1) -> Chunk:
    return Chunk(
        chunk_id=f"chunk_{n:04d}",
        jurisdiction="EU",
        source="EURLEX",
        source_id="32013R0575",
        hierarchy_path=f"CRR > Art. {n}",
        publication_date=date(2013, 6, 27),
        text=text,
    )


def _mock_response(context_text: str) -> MagicMock:
    content = MagicMock()
    content.text = context_text
    usage = MagicMock()
    usage.cache_read_input_tokens = 100
    usage.cache_creation_input_tokens = 0
    resp = MagicMock()
    resp.content = [content]
    resp.usage = usage
    return resp


class TestCacheControlInSystemMessage:
    def test_cache_control_in_system_message(self, tmp_path: Path) -> None:
        anthropic_mock = MagicMock()
        anthropic_mock.messages.create.return_value = _mock_response("Contexto del artículo 92.")

        ctx = Contextualizer(anthropic_client=anthropic_mock, cache_dir=tmp_path)
        doc = _make_doc()
        chunk = _make_chunk("Los fondos propios deben ser del 8%.", 92)

        ctx.enrich(doc, [chunk])

        call_kwargs = anthropic_mock.messages.create.call_args
        system_blocks = call_kwargs.kwargs.get("system") or call_kwargs.args[0] if call_kwargs.args else []
        system_blocks = call_kwargs.kwargs.get("system", [])

        # One of the system blocks must have cache_control: {"type": "ephemeral"}
        cache_controlled = [
            b for b in system_blocks
            if isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
        ]
        assert len(cache_controlled) >= 1

    def test_document_text_in_system_message(self, tmp_path: Path) -> None:
        anthropic_mock = MagicMock()
        anthropic_mock.messages.create.return_value = _mock_response("Contexto.")

        ctx = Contextualizer(anthropic_client=anthropic_mock, cache_dir=tmp_path)
        doc = _make_doc()
        chunk = _make_chunk("Texto del chunk.")

        ctx.enrich(doc, [chunk])

        system_blocks = anthropic_mock.messages.create.call_args.kwargs.get("system", [])
        all_text = " ".join(b.get("text", "") for b in system_blocks if isinstance(b, dict))
        assert doc.full_text[:50] in all_text


class TestLocalCacheAvoidsApiCalls:
    def test_local_cache_skips_api_on_second_call(self, tmp_path: Path) -> None:
        anthropic_mock = MagicMock()
        anthropic_mock.messages.create.return_value = _mock_response("Contexto cacheado.")

        ctx = Contextualizer(anthropic_client=anthropic_mock, cache_dir=tmp_path)
        doc = _make_doc()
        chunk = _make_chunk("Texto.", 1)

        ctx.enrich(doc, [chunk])
        ctx.enrich(doc, [chunk])

        # API called only once — second call reads from disk cache
        assert anthropic_mock.messages.create.call_count == 1

    def test_context_text_written_to_cache(self, tmp_path: Path) -> None:
        expected = "Este artículo establece los requisitos mínimos de capital."
        anthropic_mock = MagicMock()
        anthropic_mock.messages.create.return_value = _mock_response(expected)

        ctx = Contextualizer(anthropic_client=anthropic_mock, cache_dir=tmp_path)
        doc = _make_doc()
        chunk = _make_chunk("Requisitos de capital.", 92)

        enriched = ctx.enrich(doc, [chunk])
        assert enriched[0].context_text == expected

        # File exists on disk
        assert any(tmp_path.iterdir())
