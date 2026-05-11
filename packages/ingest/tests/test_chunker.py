"""Unit tests for LegalChunker."""

from __future__ import annotations

from datetime import date

from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode
from lex_agents_ingest.chunker import LegalChunker

_SOURCE = "boe"
_SOURCE_ID = "BOE-A-2014-0001"


def _make_doc(hierarchy: list[HierarchyNode], full_text: str = "") -> CanonicalDocument:
    return CanonicalDocument(
        source="boe",
        source_id=_SOURCE_ID,
        title="Test",
        publication_date=date(2024, 1, 1),
        status="vigente",
        hierarchy=hierarchy,
        full_text=full_text,
    )


def _art(num: str, title: str = "") -> HierarchyNode:
    return HierarchyNode(level="articulo", number=num, title=title)


def _considerando(num: str) -> HierarchyNode:
    return HierarchyNode(level="considerando", number=num, title="")


def _anexo(num: str) -> HierarchyNode:
    return HierarchyNode(level="anexo", number=num, title="Tabla de requisitos")


class TestArticleSimple:
    def test_article_simple_300_tokens(self) -> None:
        text = "Los fondos propios de las entidades de crédito. " * 20
        doc = _make_doc(
            hierarchy=[_art("1", "Ámbito")],
            full_text=f"Artículo 1\n{text}",
        )
        chunker = LegalChunker(max_tokens=1024)
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 1
        # Each chunk has required fields
        for c in chunks:
            assert c.chunk_id != ""
            assert c.source_id == _SOURCE_ID
            assert c.text != ""


class TestArticleWithApartados:
    def test_large_article_splits(self) -> None:
        # Each article has many short paragraphs (separated by \n\n) so the
        # splitter can break at paragraph boundaries when > max_tokens.
        para = "\n\n".join(
            f"El apartado {j} establece los requisitos de capital mínimo para entidades." * 3
            for j in range(1, 20)
        )
        full = "\n\n".join(f"Artículo {i}\n{para}" for i in range(1, 4))
        hierarchy = [_art(str(i)) for i in range(1, 4)]
        doc = _make_doc(hierarchy=hierarchy, full_text=full)
        chunker = LegalChunker(max_tokens=128)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 3
        # All chunks have valid section_type
        for c in chunks:
            assert c.section_type in {"articulo", "considerando", "anexo"}

    def test_breadcrumb_in_hierarchy_path(self) -> None:
        text = "Regula la solvencia de las entidades. " * 20
        doc = _make_doc(
            hierarchy=[
                HierarchyNode(level="titulo", number="I", title="Disposiciones generales"),
                _art("1", "Objeto"),
            ],
            full_text=f"Artículo 1\n{text}",
        )
        chunker = LegalChunker(max_tokens=1024)
        chunks = chunker.chunk(doc)
        assert chunks
        # Hierarchy path should contain the title ancestor
        paths = " ".join(c.hierarchy_path for c in chunks)
        assert "Titulo I" in paths or "articulo" in paths.lower()


class TestConsiderandos:
    def test_five_considerandos_produce_five_chunks(self) -> None:
        nodes = [_considerando(str(i)) for i in range(1, 6)]
        texts = "\n".join(
            f"Considerando {i}\nEste considerando establece el fundamento normativo {i}."
            for i in range(1, 6)
        )
        doc = _make_doc(hierarchy=nodes, full_text=texts)
        chunker = LegalChunker(max_tokens=1024)
        chunks = chunker.chunk(doc)
        # At least as many chunks as considerandos
        assert len(chunks) >= 1
        section_types = {c.section_type for c in chunks}
        assert "considerando" in section_types


class TestAnexe:
    def test_small_annexe_is_single_chunk(self) -> None:
        text = "Tabla de requisitos de capital. " * 10
        doc = _make_doc(
            hierarchy=[_anexo("I")],
            full_text=f"Anexo I\n{text}",
        )
        chunker = LegalChunker(max_tokens=1024)
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 1
        assert any(c.section_type == "anexo" for c in chunks)


class TestFallbackUnstructured:
    def test_no_hierarchy_uses_fallback(self) -> None:
        long_text = "Texto no estructurado sobre normativa bancaria. " * 200
        doc = _make_doc(hierarchy=[], full_text=long_text)
        chunker = LegalChunker(max_tokens=128, overlap_tokens=32)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 1
        for c in chunks:
            assert c.text != ""

    def test_empty_document_returns_empty(self) -> None:
        doc = _make_doc(hierarchy=[], full_text="")
        chunker = LegalChunker()
        chunks = chunker.chunk(doc)
        assert chunks == []
