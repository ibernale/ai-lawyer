"""Unit tests for the RRF merging logic in HybridRetriever."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lex_agents_rag.retriever import HybridRetriever, RankedChunk


def _make_hit(chunk_id: str, text: str = "text") -> MagicMock:
    hit = MagicMock()
    hit.id = chunk_id
    hit.payload = {
        "chunk_id": chunk_id,
        "text": text,
        "context_text": "",
        "source_id": "TEST",
        "hierarchy_path": f"path/{chunk_id}",
    }
    return hit


def _retriever() -> HybridRetriever:
    return HybridRetriever(
        qdrant_client=MagicMock(),
        embedder=MagicMock(),
    )


class TestRrfBasic:
    def test_rrf_basic_scores(self) -> None:
        retriever = _retriever()
        dense = [_make_hit("a"), _make_hit("b"), _make_hit("c")]
        sparse = [_make_hit("a"), _make_hit("c"), _make_hit("b")]

        result = retriever._rrf(dense, sparse, k=60)
        scores = {r.chunk_id: r.score for r in result}

        # "a" is rank-1 in both → highest score
        assert scores["a"] > scores["b"]
        assert scores["a"] > scores["c"]
        # Manually verify: a = 1/61 + 1/61 ≈ 0.03279
        expected_a = 1 / (60 + 1) + 1 / (60 + 1)
        assert abs(scores["a"] - expected_a) < 1e-9


class TestRrfNoOverlap:
    def test_no_overlap_all_appear(self) -> None:
        retriever = _retriever()
        dense = [_make_hit("a"), _make_hit("b")]
        sparse = [_make_hit("c"), _make_hit("d")]

        result = retriever._rrf(dense, sparse)
        ids = {r.chunk_id for r in result}
        assert ids == {"a", "b", "c", "d"}


class TestRrfFullOverlap:
    def test_full_overlap_max_score(self) -> None:
        retriever = _retriever()
        hits = [_make_hit("x"), _make_hit("y"), _make_hit("z")]

        result = retriever._rrf(hits, hits, k=60)
        # Same doc in both lists at same rank → score = 2 × 1/(k+rank)
        for r in result:
            manual = 2.0 / (60 + r.rank)
            assert abs(r.score - manual) < 1e-9

    def test_results_ordered_by_score(self) -> None:
        retriever = _retriever()
        hits = [_make_hit(str(i)) for i in range(5)]
        result = retriever._rrf(hits, hits)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)
