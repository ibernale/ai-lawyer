"""Unit tests for CRAGFilter."""

from __future__ import annotations

from unittest.mock import MagicMock

from lex_agents_rag.crag import CRAGFilter, _parse_classifications
from lex_agents_rag.retriever import RankedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id: str, rank: int = 1) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        score=1.0 / rank,
        rank=rank,
        metadata={"chunk_id": chunk_id},
        text=f"Fragmento normativo sobre {chunk_id}.",
        context_text="",
        source_label=f"DOC — {chunk_id}",
    )


def _make_chunks(n: int) -> list[RankedChunk]:
    return [_make_chunk(f"c{i}", rank=i + 1) for i in range(n)]


def _make_anthropic_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def _make_client(classification_text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = _make_anthropic_response(classification_text)
    return client


# ---------------------------------------------------------------------------
# _parse_classifications (unit)
# ---------------------------------------------------------------------------


class TestParseClassifications:
    def test_parses_standard_format(self) -> None:
        raw = "1:R\n2:I\n3:U"
        result = _parse_classifications(raw)
        assert result == {1: "R", 2: "I", 3: "U"}

    def test_handles_lowercase(self) -> None:
        raw = "1:r\n2:i\n3:u"
        result = _parse_classifications(raw)
        assert result == {1: "R", 2: "I", 3: "U"}

    def test_ignores_malformed_lines(self) -> None:
        raw = "1:R\nnot a valid line\n3:I"
        result = _parse_classifications(raw)
        assert result == {1: "R", 3: "I"}

    def test_empty_string_returns_empty(self) -> None:
        assert _parse_classifications("") == {}

    def test_handles_whitespace_around_delimiter(self) -> None:
        raw = "  1 : R  \n  2 : I  "
        result = _parse_classifications(raw)
        assert result == {1: "R", 2: "I"}


# ---------------------------------------------------------------------------
# CRAGFilter.filter — skip when few chunks
# ---------------------------------------------------------------------------


class TestCRAGFilterSkipWhenFewChunks:
    def test_returns_all_when_five_or_fewer(self) -> None:
        client = MagicMock()  # Should not be called
        f = CRAGFilter(anthropic_client=client)

        for n in range(1, 6):
            chunks = _make_chunks(n)
            result = f.filter("query", chunks)
            assert result == chunks
            client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# CRAGFilter.filter — normal filtering
# ---------------------------------------------------------------------------


class TestCRAGFilterNormalFiltering:
    def test_removes_irrelevant_chunks(self) -> None:
        # 6 chunks (chunk_ids c0–c5); 1-based LLM indices map: 1→c0, 2→c1, 3→c2, 4→c3, 5→c4, 6→c5
        # Classify indices 2 and 4 as irrelevant → c1 and c3 should be removed
        chunks = _make_chunks(6)
        classification = "1:R\n2:I\n3:R\n4:I\n5:U\n6:R"
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query CET1", chunks)

        kept_ids = {c.chunk_id for c in result}
        assert "c0" in kept_ids   # index 1: R
        assert "c2" in kept_ids   # index 3: R
        assert "c4" in kept_ids   # index 5: U (uncertain → kept)
        assert "c5" in kept_ids   # index 6: R
        assert "c1" not in kept_ids  # index 2: I — removed
        assert "c3" not in kept_ids  # index 4: I — removed

    def test_irrelevant_chunks_excluded(self) -> None:
        chunks = _make_chunks(6)
        # Mark chunks at 1-based indices 1, 3 as irrelevant
        classification = "1:I\n2:R\n3:I\n4:R\n5:U\n6:R"
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks)

        result_ids = [c.chunk_id for c in result]
        # chunk at index 1 = c0, index 3 = c2
        assert "c0" not in result_ids
        assert "c2" not in result_ids
        assert "c1" in result_ids
        assert "c3" in result_ids

    def test_respects_max_to_keep(self) -> None:
        chunks = _make_chunks(10)
        # All relevant
        classification = "\n".join(f"{i}:R" for i in range(1, 11))
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks, max_to_keep=5)

        assert len(result) <= 5

    def test_preserves_original_order(self) -> None:
        chunks = _make_chunks(7)
        # Keep all except index 4
        classification = "1:R\n2:R\n3:R\n4:I\n5:R\n6:U\n7:R"
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks)

        # Remaining should still be in original rank order
        for a, b in zip(result, result[1:]):
            assert a.rank < b.rank


# ---------------------------------------------------------------------------
# CRAGFilter.filter — fallback when too aggressive
# ---------------------------------------------------------------------------


class TestCRAGFilterFallbackWhenTooAggressive:
    def test_returns_top5_when_filter_leaves_fewer_than_5(self) -> None:
        chunks = _make_chunks(10)
        # Mark 9 out of 10 as irrelevant → only 1 survives → too aggressive
        classification = "1:R\n" + "\n".join(f"{i}:I" for i in range(2, 11))
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks)

        # Fallback: return top-3 originals (1 < _MIN_CHUNKS_AFTER_FILTER=3)
        assert len(result) == 3
        assert [c.chunk_id for c in result] == [c.chunk_id for c in chunks[:3]]

    def test_fallback_exactly_2_survivors(self) -> None:
        chunks = _make_chunks(8)
        # 2 survivors — triggers fallback (< _MIN_CHUNKS_AFTER_FILTER=3)
        classification = "1:R\n2:R\n3:I\n4:I\n5:I\n6:I\n7:I\n8:I"
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks)

        # 2 < 3 → fallback to top-3 originals
        assert len(result) == 3
        assert [c.chunk_id for c in result] == [c.chunk_id for c in chunks[:3]]


# ---------------------------------------------------------------------------
# CRAGFilter.filter — fallback on Claude failure
# ---------------------------------------------------------------------------


class TestCRAGFilterFallbackOnError:
    def test_returns_originals_when_claude_raises(self) -> None:
        chunks = _make_chunks(8)
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("network error")

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks)

        # Must not raise and must return valid chunks
        assert isinstance(result, list)
        assert len(result) > 0
        # Should be the originals (capped)
        assert all(c.chunk_id.startswith("c") for c in result)

    def test_does_not_crash_on_partial_parse(self) -> None:
        chunks = _make_chunks(7)
        # Response is partially malformed — some lines are junk
        classification = "1:R\nbad line\n3:I\n!!!\n5:U"
        client = _make_client(classification)

        f = CRAGFilter(anthropic_client=client)
        result = f.filter("query", chunks)

        # Chunk at index 3 (0-based: c2) classified I → removed
        # Others with no classification default to "U" (kept)
        result_ids = [c.chunk_id for c in result]
        assert "c2" not in result_ids  # index 3:I
        assert isinstance(result, list)
