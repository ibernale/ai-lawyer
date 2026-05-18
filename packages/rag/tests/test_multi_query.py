"""Unit tests for MultiQueryRetriever."""

from __future__ import annotations

from unittest.mock import MagicMock

from lex_agents_rag.multi_query_retriever import MultiQueryRetriever, _fuse_with_rrf
from lex_agents_rag.retriever import RankedChunk, SearchFilters

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id: str, score: float = 0.5, rank: int = 1) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        score=score,
        rank=rank,
        metadata={"chunk_id": chunk_id},
        text=f"Texto del chunk {chunk_id}",
        context_text="",
        source_label=f"DOC — {chunk_id}",
    )


def _make_anthropic_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def _make_base_retriever(result_map: dict[str, list[RankedChunk]]) -> MagicMock:
    """Return a mock HybridRetriever whose search() uses result_map keyed by query."""
    retriever = MagicMock()
    retriever.search.side_effect = lambda q, filters=None, k_rrf=30: result_map.get(
        q, []
    )
    return retriever


# ---------------------------------------------------------------------------
# _fuse_with_rrf (unit)
# ---------------------------------------------------------------------------


class TestFuseWithRrf:
    def test_deduplicates_by_chunk_id(self) -> None:
        shared = _make_chunk("shared", score=0.9, rank=1)
        list_a = [shared, _make_chunk("a_only", rank=2)]
        list_b = [shared, _make_chunk("b_only", rank=2)]

        fused = _fuse_with_rrf([list_a, list_b])
        ids = [c.chunk_id for c in fused]

        assert ids.count("shared") == 1

    def test_shared_chunk_ranks_first(self) -> None:
        shared = _make_chunk("shared")
        list_a = [shared, _make_chunk("a_only")]
        list_b = [shared, _make_chunk("b_only")]

        fused = _fuse_with_rrf([list_a, list_b])
        assert fused[0].chunk_id == "shared"

    def test_rrf_scores_are_positive(self) -> None:
        chunks = [_make_chunk(f"c{i}", rank=i + 1) for i in range(5)]
        fused = _fuse_with_rrf([chunks])
        assert all(c.score > 0 for c in fused)

    def test_rank_reflects_position(self) -> None:
        chunks = [_make_chunk(f"c{i}") for i in range(3)]
        fused = _fuse_with_rrf([chunks])
        for expected_rank, chunk in enumerate(fused, start=1):
            assert chunk.rank == expected_rank

    def test_empty_lists(self) -> None:
        assert _fuse_with_rrf([]) == []
        assert _fuse_with_rrf([[]]) == []


# ---------------------------------------------------------------------------
# MultiQueryRetriever.search
# ---------------------------------------------------------------------------


class TestMultiQueryRetrieverSearch:
    def _make_retriever(
        self,
        queries_to_results: dict[str, list[RankedChunk]],
        paraphrase_text: str = "¿Cuáles son los requisitos de capital?\n¿Qué exige el regulador?",
        n_queries: int = 2,
    ) -> tuple[MultiQueryRetriever, MagicMock, MagicMock]:
        base = _make_base_retriever(queries_to_results)
        client = MagicMock()
        client.messages.create.return_value = _make_anthropic_response(paraphrase_text)

        mq = MultiQueryRetriever(
            base_retriever=base,
            anthropic_client=client,
            n_queries=n_queries,
        )
        return mq, base, client

    def test_search_deduplicates_cross_queries(self) -> None:
        shared_chunk = _make_chunk("shared")
        results = {
            "capital CET1": [shared_chunk, _make_chunk("only_q0")],
            "¿Cuáles son los requisitos de capital?": [
                shared_chunk,
                _make_chunk("only_q1"),
            ],
            "¿Qué exige el regulador?": [shared_chunk, _make_chunk("only_q2")],
        }

        mq, _, _ = self._make_retriever(results)
        fused = mq.search("capital CET1", k=20)

        ids = [c.chunk_id for c in fused]
        assert ids.count("shared") == 1

    def test_shared_chunk_ranked_higher(self) -> None:
        shared_chunk = _make_chunk("shared")
        results = {
            "capital": [shared_chunk, _make_chunk("x")],
            "¿Cuáles son los requisitos de capital?": [shared_chunk, _make_chunk("y")],
            "¿Qué exige el regulador?": [_make_chunk("z")],
        }

        mq, _, _ = self._make_retriever(results)
        fused = mq.search("capital", k=10)

        assert fused[0].chunk_id == "shared"

    def test_search_respects_k_limit(self) -> None:
        results = {
            "q": [_make_chunk(f"c{i}") for i in range(20)],
            "¿Cuáles son los requisitos de capital?": [
                _make_chunk(f"p{i}") for i in range(20)
            ],
            "¿Qué exige el regulador?": [_make_chunk(f"r{i}") for i in range(20)],
        }

        mq, _, _ = self._make_retriever(results)
        fused = mq.search("q", k=5)

        assert len(fused) <= 5

    def test_filters_forwarded_to_base(self) -> None:
        mq, base, _ = self._make_retriever({})
        filters = SearchFilters(jurisdiction="EU")
        mq.search("query", filters=filters, k=5)

        for call in base.search.call_args_list:
            assert call.kwargs.get("filters") == filters or (
                len(call.args) > 1 and call.args[1] == filters
            )


# ---------------------------------------------------------------------------
# Fallback on Claude failure
# ---------------------------------------------------------------------------


class TestMultiQueryRetrieverFallback:
    def test_falls_back_when_claude_raises(self) -> None:
        fallback_chunks = [_make_chunk(f"fb{i}") for i in range(5)]
        base = MagicMock()
        base.search.return_value = fallback_chunks

        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API error")

        mq = MultiQueryRetriever(
            base_retriever=base,
            anthropic_client=client,
            n_queries=3,
        )
        result = mq.search("query sobre capital")

        # Must not raise and must return a valid list
        assert isinstance(result, list)
        # Base retriever still called at least once (for the original query)
        assert base.search.called
