"""Unit tests for ContextAssembler."""

from __future__ import annotations

from lex_agents_rag.assembler import ContextAssembler
from lex_agents_rag.retriever import RankedChunk


def _make_chunk(n: int, source_id: str = "32013R0575") -> RankedChunk:
    return RankedChunk(
        chunk_id=f"chunk_{n:04d}",
        score=1.0 / n,
        rank=n,
        metadata={
            "source_id": source_id,
            "hierarchy_path": f"CRR > Art. {n}",
        },
        text=f"Texto del artículo {n} sobre requisitos de capital.",
        context_text=f"Contexto del artículo {n}.",
        source_label=f"{source_id} — Art. {n}",
    )


class TestCitationIndicesSequential:
    def test_indices_start_at_one(self) -> None:
        assembler = ContextAssembler()
        chunks = [_make_chunk(i) for i in range(1, 6)]
        result = assembler.assemble(chunks)

        indices = [m.index for m in result.citation_mapping]
        assert indices == list(range(1, 6))

    def test_single_chunk_index_is_one(self) -> None:
        assembler = ContextAssembler()
        result = assembler.assemble([_make_chunk(1)])
        assert result.citation_mapping[0].index == 1


class TestAllChunksInMapping:
    def test_all_chunks_appear_in_mapping(self) -> None:
        assembler = ContextAssembler()
        n = 7
        chunks = [_make_chunk(i) for i in range(1, n + 1)]
        result = assembler.assemble(chunks)

        assert len(result.citation_mapping) == n
        chunk_ids = {c.chunk_id for c in chunks}
        mapping_ids = {m.chunk_id for m in result.citation_mapping}
        assert chunk_ids == mapping_ids

    def test_context_text_appears_in_output(self) -> None:
        assembler = ContextAssembler()
        chunk = _make_chunk(1)
        result = assembler.assemble([chunk])
        assert "[REF:1]" in result.context_text
        assert chunk.text in result.context_text

    def test_empty_chunks_returns_empty(self) -> None:
        assembler = ContextAssembler()
        result = assembler.assemble([])
        assert result.context_text == ""
        assert result.citation_mapping == []
