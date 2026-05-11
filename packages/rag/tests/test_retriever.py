"""Unit tests for HybridRetriever — mocked Qdrant."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lex_agents_rag.retriever import HybridRetriever, SearchFilters


def _make_hit(chunk_id: str, score: float = 1.0) -> MagicMock:
    hit = MagicMock()
    hit.id = chunk_id
    hit.payload = {
        "chunk_id": chunk_id,
        "text": f"Texto de {chunk_id}",
        "context_text": "",
        "source_id": "TEST",
        "hierarchy_path": f"path/{chunk_id}",
    }
    return hit


def _make_query_result(hits: list[MagicMock]) -> MagicMock:
    result = MagicMock()
    result.points = hits
    return result


class TestSearchReturnsMergedResults:
    def test_search_returns_rrf_merged(self) -> None:
        qdrant = MagicMock()
        embedder = MagicMock()
        embedder.embed_batch.return_value = [
            MagicMock(dense=[0.1] * 1024, sparse={1: 0.5, 2: 0.3})
        ]

        dense_hits = [_make_hit(f"d{i}") for i in range(3)]
        sparse_hits = [_make_hit(f"s{i}") for i in range(3)]
        qdrant.query_points.side_effect = [
            _make_query_result(dense_hits),
            _make_query_result(sparse_hits),
        ]

        retriever = HybridRetriever(qdrant_client=qdrant, embedder=embedder)
        results = retriever.search("requisitos de capital CET1", k_rrf=5)

        assert len(results) <= 5
        assert all(r.chunk_id != "" for r in results)
        # RRF scores should be positive
        assert all(r.score > 0 for r in results)

    def test_overlap_chunk_ranks_higher(self) -> None:
        qdrant = MagicMock()
        embedder = MagicMock()
        embedder.embed_batch.return_value = [
            MagicMock(dense=[0.1] * 1024, sparse={1: 0.5})
        ]

        shared = _make_hit("shared")
        dense_hits = [shared, _make_hit("dense_only")]
        sparse_hits = [shared, _make_hit("sparse_only")]
        qdrant.query_points.side_effect = [
            _make_query_result(dense_hits),
            _make_query_result(sparse_hits),
        ]

        retriever = HybridRetriever(qdrant_client=qdrant, embedder=embedder)
        results = retriever.search("query")
        ids = [r.chunk_id for r in results]
        assert ids.index("shared") < ids.index("dense_only")
        assert ids.index("shared") < ids.index("sparse_only")


class TestFiltersPassedToQdrant:
    def test_filters_passed_to_qdrant(self) -> None:
        qdrant = MagicMock()
        embedder = MagicMock()
        embedder.embed_batch.return_value = [
            MagicMock(dense=[0.1] * 1024, sparse={})
        ]
        qdrant.query_points.return_value = _make_query_result([])

        retriever = HybridRetriever(qdrant_client=qdrant, embedder=embedder)
        sf = SearchFilters(jurisdiction="EU", status="vigente")
        retriever.search("query", filters=sf)

        calls = qdrant.query_points.call_args_list
        assert len(calls) == 2
        # Both calls should have query_filter set (not None)
        for call in calls:
            assert call.kwargs.get("query_filter") is not None
