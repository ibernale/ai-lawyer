"""Unit tests for MultiQueryRetriever."""

from __future__ import annotations

from unittest.mock import MagicMock

from anthropic.types import TextBlock
from lex_agents_rag.multi_query_retriever import _RRF_K, MultiQueryRetriever
from lex_agents_rag.retriever import RankedChunk, SearchFilters

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(chunk_id: str, rank: int, score: float = 1.0) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        score=score,
        rank=rank,
        metadata={},
        text=f"Texto jurídico para {chunk_id}",
        context_text="",
        source_label="test",
    )


def _make_client(paraphrase_text: str = "paráfrasis 1\nparáfrasis 2") -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(spec=TextBlock, text=paraphrase_text)]
    client.messages_create.return_value = resp
    return client


def _make_retriever(*result_lists: list[RankedChunk]) -> MagicMock:
    retriever = MagicMock()
    retriever.search.side_effect = list(result_lists)
    return retriever


# ── paraphrase generation ─────────────────────────────────────────────────────

def test_generate_paraphrases_success() -> None:
    client = _make_client("versión alternativa 1\nversión alternativa 2")
    mq = MultiQueryRetriever(MagicMock(), client, n_queries=3)
    paraphrases = mq._generate_paraphrases("¿Qué es el ratio de capital CET1?")
    assert len(paraphrases) == 2
    assert "versión alternativa 1" in paraphrases


def test_generate_paraphrases_limited_to_n_minus_1() -> None:
    # API returns 5 lines but n_queries=3 → only 2 paraphrases
    client = _make_client("línea1\nlínea2\nlínea3\nlínea4\nlínea5")
    mq = MultiQueryRetriever(MagicMock(), client, n_queries=3)
    paraphrases = mq._generate_paraphrases("consulta")
    assert len(paraphrases) == 2


def test_generate_paraphrases_empty_when_n_queries_1() -> None:
    client = _make_client("no debería llamarse")
    mq = MultiQueryRetriever(MagicMock(), client, n_queries=1)
    paraphrases = mq._generate_paraphrases("consulta")
    assert paraphrases == []
    client.messages_create.assert_not_called()


def test_generate_paraphrases_returns_empty_on_failure() -> None:
    client = MagicMock()
    client.messages_create.side_effect = RuntimeError("API error")
    mq = MultiQueryRetriever(MagicMock(), client, n_queries=3)
    paraphrases = mq._generate_paraphrases("consulta")
    assert paraphrases == []


def test_generate_paraphrases_skips_blank_lines() -> None:
    client = _make_client("paráfrasis 1\n\n\nparáfrasis 2\n")
    mq = MultiQueryRetriever(MagicMock(), client, n_queries=3)
    paraphrases = mq._generate_paraphrases("consulta")
    assert paraphrases == ["paráfrasis 1", "paráfrasis 2"]


# ── RRF fusion ────────────────────────────────────────────────────────────────

def test_fuse_with_rrf_deduplicates() -> None:
    mq = MultiQueryRetriever(MagicMock(), MagicMock())
    c1 = _make_chunk("A", rank=1)
    c2 = _make_chunk("B", rank=2)
    merged = mq._fuse_with_rrf([[c1, c2], [c1, c2]], k=10)
    ids = [c.chunk_id for c in merged]
    assert ids.count("A") == 1
    assert ids.count("B") == 1


def test_fuse_with_rrf_score_accumulation_drives_ranking() -> None:
    mq = MultiQueryRetriever(MagicMock(), MagicMock())
    c_a = _make_chunk("A", rank=1)
    c_b = _make_chunk("B", rank=1)
    # A appears in both lists at rank 1 → higher cumulative score
    merged = mq._fuse_with_rrf([[c_a], [c_a, c_b]], k=10)
    assert merged[0].chunk_id == "A"


def test_fuse_with_rrf_respects_k() -> None:
    mq = MultiQueryRetriever(MagicMock(), MagicMock())
    chunks = [_make_chunk(f"C{i}", rank=i + 1) for i in range(20)]
    merged = mq._fuse_with_rrf([chunks], k=5)
    assert len(merged) == 5


def test_fuse_with_rrf_assigns_sequential_ranks() -> None:
    mq = MultiQueryRetriever(MagicMock(), MagicMock())
    chunks = [_make_chunk("A", rank=5), _make_chunk("B", rank=3)]
    merged = mq._fuse_with_rrf([chunks], k=10)
    for i, chunk in enumerate(merged, start=1):
        assert chunk.rank == i


def test_fuse_with_rrf_empty_input_returns_empty() -> None:
    mq = MultiQueryRetriever(MagicMock(), MagicMock())
    assert mq._fuse_with_rrf([], k=10) == []


def test_fuse_with_rrf_rrf_k_constant_used() -> None:
    """Score at rank 1 should be 1 / (_RRF_K + 1)."""
    mq = MultiQueryRetriever(MagicMock(), MagicMock())
    chunk = _make_chunk("A", rank=1)
    merged = mq._fuse_with_rrf([[chunk]], k=1)
    expected_score = 1.0 / (_RRF_K + 1)
    assert abs(merged[0].score - expected_score) < 1e-10


# ── end-to-end search ─────────────────────────────────────────────────────────

def test_search_calls_retriever_once_per_query() -> None:
    chunk_a = _make_chunk("A", rank=1)
    chunk_b = _make_chunk("B", rank=1)
    retriever = _make_retriever([chunk_a], [chunk_b], [chunk_a])
    client = _make_client("paráfrasis 1\nparáfrasis 2")
    mq = MultiQueryRetriever(retriever, client, n_queries=3)
    mq.search("consulta CRR III")
    # original + 2 paraphrases = 3 retriever calls
    assert retriever.search.call_count == 3


def test_search_returns_fused_results() -> None:
    chunk_a = _make_chunk("A", rank=1)
    chunk_b = _make_chunk("B", rank=2)
    retriever = _make_retriever([chunk_a, chunk_b])
    client = _make_client("")  # empty → no paraphrases
    mq = MultiQueryRetriever(retriever, client, n_queries=3)
    results = mq.search("consulta")
    ids = {c.chunk_id for c in results}
    assert "A" in ids
    assert "B" in ids


def test_search_handles_retriever_error_gracefully() -> None:
    retriever = MagicMock()
    retriever.search.side_effect = RuntimeError("qdrant error")
    mq = MultiQueryRetriever(retriever, _make_client(""), n_queries=1)
    results = mq.search("consulta")
    assert results == []


def test_search_passes_filters_to_retriever() -> None:
    chunk = _make_chunk("A", rank=1)
    retriever = _make_retriever([chunk])
    mq = MultiQueryRetriever(retriever, _make_client(""), n_queries=1)
    filters = SearchFilters(jurisdiction="ES")
    mq.search("consulta", filters=filters, k=10)
    _, call_kwargs = retriever.search.call_args
    assert call_kwargs.get("filters") == filters or retriever.search.call_args[0][1] == filters
