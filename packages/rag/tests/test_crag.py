"""Unit tests for CRAGFilter."""

from __future__ import annotations

from unittest.mock import MagicMock

from anthropic.types import TextBlock
from lex_agents_rag.crag import (
    _MIN_CHUNKS_AFTER_FILTER,
    _MIN_CHUNKS_TO_FILTER,
    CRAGFilter,
)
from lex_agents_rag.retriever import RankedChunk

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(chunk_id: str, rank: int) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        score=1.0 / rank,
        rank=rank,
        metadata={},
        text=f"Texto normativo para {chunk_id} sobre regulación bancaria",
        context_text="",
        source_label="test",
    )


def _make_client(response_text: str) -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(spec=TextBlock, text=response_text)]
    client.messages_create.return_value = resp
    return client


# ── skip logic ────────────────────────────────────────────────────────────────

def test_filter_skips_when_at_or_below_min_threshold() -> None:
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(_MIN_CHUNKS_TO_FILTER)]
    client = _make_client("no debería llamarse")
    result = CRAGFilter(client).filter("consulta", chunks)
    client.messages_create.assert_not_called()
    assert result == chunks


def test_filter_skips_empty_input() -> None:
    client = _make_client("")
    result = CRAGFilter(client).filter("consulta", [])
    client.messages_create.assert_not_called()
    assert result == []


def test_filter_calls_llm_when_above_threshold() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 1
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    labels = "\n".join(f"{i+1}: R" for i in range(n))
    client = _make_client(labels)
    CRAGFilter(client).filter("consulta", chunks)
    client.messages_create.assert_called_once()


# ── parse_classifications ─────────────────────────────────────────────────────

def test_parse_basic_labels() -> None:
    raw = "1: R\n2: I\n3: U\n4: R"
    labels = CRAGFilter._parse_classifications(raw, 4)
    assert labels == ["R", "I", "U", "R"]


def test_parse_lowercase_labels() -> None:
    labels = CRAGFilter._parse_classifications("1: r\n2: i\n3: u", 3)
    assert labels == ["R", "I", "U"]


def test_parse_missing_entry_defaults_to_U() -> None:
    labels = CRAGFilter._parse_classifications("1: R\n3: I", 3)
    assert labels == ["R", "U", "I"]


def test_parse_ignores_noise_lines() -> None:
    raw = "Aquí los resultados:\n1: R\n2: I\nGracias."
    labels = CRAGFilter._parse_classifications(raw, 2)
    assert labels == ["R", "I"]


def test_parse_returns_correct_length() -> None:
    labels = CRAGFilter._parse_classifications("", 5)
    assert len(labels) == 5
    assert all(label == "U" for label in labels)


# ── relevance filtering ───────────────────────────────────────────────────────

def test_removes_irrelevant_chunk() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 1
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    # Mark chunk at index 2 (C2) as irrelevant
    labels = "\n".join(
        f"{i+1}: {'I' if i == 2 else 'R'}" for i in range(n)
    )
    result = CRAGFilter(_make_client(labels)).filter("consulta CRR", chunks)
    ids = {c.chunk_id for c in result}
    assert "C2" not in ids
    assert len(result) == n - 1


def test_all_relevant_chunks_kept() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 2
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    labels = "\n".join(f"{i+1}: R" for i in range(n))
    result = CRAGFilter(_make_client(labels)).filter("consulta", chunks)
    assert len(result) == n


def test_uncertain_chunks_are_kept() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 1
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    labels = "\n".join(f"{i+1}: U" for i in range(n))
    result = CRAGFilter(_make_client(labels)).filter("consulta", chunks)
    assert len(result) == n


def test_exactly_min_after_filter_survives() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 2
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    # Only first _MIN_CHUNKS_AFTER_FILTER are relevant — should keep them all
    labels = "\n".join(
        f"{i+1}: {'R' if i < _MIN_CHUNKS_AFTER_FILTER else 'I'}" for i in range(n)
    )
    result = CRAGFilter(_make_client(labels)).filter("consulta", chunks)
    assert len(result) == _MIN_CHUNKS_AFTER_FILTER


def test_fallback_when_too_few_survive() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 3
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    # All irrelevant → fallback to top _MIN_CHUNKS_AFTER_FILTER by rank
    labels = "\n".join(f"{i+1}: I" for i in range(n))
    result = CRAGFilter(_make_client(labels)).filter("consulta", chunks)
    assert len(result) == _MIN_CHUNKS_AFTER_FILTER
    assert result[0].rank <= result[-1].rank  # ordered by rank ascending


def test_fallback_on_llm_error_returns_original() -> None:
    n = _MIN_CHUNKS_TO_FILTER + 2
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    client = MagicMock()
    client.messages_create.side_effect = RuntimeError("API error")
    result = CRAGFilter(client).filter("consulta", chunks)
    assert len(result) == n  # unchanged


def test_max_to_keep_limits_classified_chunks() -> None:
    n = 15
    chunks = [_make_chunk(f"C{i}", i + 1) for i in range(n)]
    labels = "\n".join(f"{i+1}: R" for i in range(10))
    result = CRAGFilter(_make_client(labels)).filter("consulta", chunks, max_to_keep=10)
    assert len(result) <= 10
