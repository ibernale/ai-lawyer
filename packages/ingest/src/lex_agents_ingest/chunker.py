"""Legal document chunker — splits CanonicalDocument into retrieval-ready Chunks."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog
import tiktoken

from lex_agents_ingest.canonical import Chunk, CanonicalDocument, HierarchyNode

if TYPE_CHECKING:
    pass

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _chunk_id(source_id: str, hierarchy_path: str) -> str:
    return hashlib.sha256(f"{source_id}::{hierarchy_path}".encode()).hexdigest()


def _breadcrumb(nodes: list[HierarchyNode]) -> str:
    return " > ".join(
        f"{n.level.capitalize()} {n.number}" + (f" {n.title}" if n.title else "")
        for n in nodes
    )


class LegalChunker:
    """Chunk a CanonicalDocument into Chunks sized for BGE-M3 (target ≤ max_tokens).

    Strategy by section_type:
    - articulo: whole article if ≤ max_tokens; else split by apartado (paragraph)
    - considerando: each recital → one chunk
    - anexo: whole annex if ≤ max_tokens; else split by sub-sections
    - fallback: sliding-window semantic chunking with overlap
    """

    def __init__(self, max_tokens: int = 1024, overlap_tokens: int = 128) -> None:
        self._max_tokens = max_tokens
        self._overlap = overlap_tokens

    def chunk(self, doc: CanonicalDocument) -> list[Chunk]:
        if not doc.hierarchy:
            return self._fallback_chunk(doc)

        chunks: list[Chunk] = []
        ancestors: list[HierarchyNode] = []

        for node in doc.hierarchy:
            if node.level == "considerando":
                chunks.extend(self._chunk_considerando(doc, node, ancestors))
            elif node.level == "anexo":
                chunks.extend(self._chunk_anexo(doc, node, ancestors))
            elif node.level == "articulo":
                chunks.extend(self._chunk_articulo(doc, node, ancestors))
            else:
                # structural node (titulo, capitulo, …): track as ancestor context
                ancestors = self._update_ancestors(ancestors, node)

        if not chunks:
            chunks = self._fallback_chunk(doc)

        logger.debug("chunked", source_id=doc.source_id, n_chunks=len(chunks))
        return chunks

    # ------------------------------------------------------------------
    # Article chunking
    # ------------------------------------------------------------------

    def _chunk_articulo(
        self, doc: CanonicalDocument, node: HierarchyNode, ancestors: list[HierarchyNode]
    ) -> list[Chunk]:
        text = self._node_text(doc, node)
        breadcrumb = _breadcrumb([*ancestors, node])

        if _count_tokens(text) <= self._max_tokens:
            return [self._make_chunk(doc, text, breadcrumb, "articulo")]

        # Split by apartados (paragraphs — each paragraph in the node text)
        return self._split_text_into_chunks(
            doc, text, breadcrumb, "articulo", node
        )

    # ------------------------------------------------------------------
    # Considerando chunking
    # ------------------------------------------------------------------

    def _chunk_considerando(
        self, doc: CanonicalDocument, node: HierarchyNode, ancestors: list[HierarchyNode]
    ) -> list[Chunk]:
        text = self._node_text(doc, node)
        breadcrumb = _breadcrumb([*ancestors, node])
        if not text.strip():
            return []
        return [self._make_chunk(doc, text, breadcrumb, "considerando")]

    # ------------------------------------------------------------------
    # Annex chunking
    # ------------------------------------------------------------------

    def _chunk_anexo(
        self, doc: CanonicalDocument, node: HierarchyNode, ancestors: list[HierarchyNode]
    ) -> list[Chunk]:
        text = self._node_text(doc, node)
        breadcrumb = _breadcrumb([*ancestors, node])

        if _count_tokens(text) <= self._max_tokens:
            return [self._make_chunk(doc, text, breadcrumb, "anexo")]

        return self._split_text_into_chunks(doc, text, breadcrumb, "anexo", node)

    # ------------------------------------------------------------------
    # Fallback: semantic sliding window
    # ------------------------------------------------------------------

    def _fallback_chunk(self, doc: CanonicalDocument) -> list[Chunk]:
        if not doc.full_text:
            return []

        tokens = _ENCODING.encode(doc.full_text)
        step = self._max_tokens - self._overlap
        chunks: list[Chunk] = []
        i = 0
        seq = 0

        while i < len(tokens):
            window = tokens[i : i + self._max_tokens]
            text = _ENCODING.decode(window)
            breadcrumb = f"{doc.source_id} > seg{seq}"
            chunks.append(self._make_chunk(doc, text, breadcrumb, "articulo"))
            i += step
            seq += 1

        return chunks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_chunk(
        self,
        doc: CanonicalDocument,
        text: str,
        hierarchy_path: str,
        section_type: str,
    ) -> Chunk:
        return Chunk(
            chunk_id=_chunk_id(doc.source_id, hierarchy_path),
            jurisdiction=doc.jurisdiction,  # type: ignore[arg-type]
            source=doc.source.upper(),
            source_id=doc.source_id,
            document_type=doc.type,
            hierarchy_path=hierarchy_path,
            section_type=section_type,
            language="es",
            publication_date=doc.publication_date,
            entry_into_force=doc.entry_into_force,
            in_force_at_indexing=doc.status == "vigente",
            checksum=doc.checksum,
            text=text,
        )

    def _node_text(self, doc: CanonicalDocument, node: HierarchyNode) -> str:
        """Extract text for a node from full_text using a heuristic search."""
        # Try to find article marker in full_text
        markers = [
            f"Artículo {node.number}",
            f"articulo {node.number}",
            f"Art. {node.number}",
            f"ARTICLE {node.number}",
            f"Considerando {node.number}",
            f"RECITAL {node.number}",
            f"Anexo {node.number}",
        ]
        text = doc.full_text
        for marker in markers:
            idx = text.find(marker)
            if idx != -1:
                # Take text from this marker to the next section marker or end
                end = self._find_next_section(text, idx + 1)
                return text[idx:end].strip()
        # Node not found in full_text — return node title as minimal text
        return f"{node.level.capitalize()} {node.number}. {node.title}"

    def _find_next_section(self, text: str, start: int) -> int:
        """Find the position of the next major section heading after start."""
        import re
        pattern = re.compile(
            r"\n(?:Artículo|articulo|Art\.|ARTICLE|Considerando|RECITAL|Anexo)\s+\d",
            re.IGNORECASE,
        )
        m = pattern.search(text, start)
        return m.start() if m else len(text)

    def _split_text_into_chunks(
        self,
        doc: CanonicalDocument,
        text: str,
        base_breadcrumb: str,
        section_type: str,
        node: HierarchyNode,
    ) -> list[Chunk]:
        """Split oversized text into sub-chunks at paragraph boundaries."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[Chunk] = []
        current: list[str] = []
        current_tokens = 0
        part = 0

        for para in paragraphs:
            para_tokens = _count_tokens(para)
            if current_tokens + para_tokens > self._max_tokens and current:
                breadcrumb = f"{base_breadcrumb} > pt{part}"
                chunks.append(
                    self._make_chunk(doc, "\n\n".join(current), breadcrumb, section_type)
                )
                part += 1
                current = []
                current_tokens = 0
            current.append(para)
            current_tokens += para_tokens

        if current:
            breadcrumb = f"{base_breadcrumb} > pt{part}" if part > 0 else base_breadcrumb
            chunks.append(
                self._make_chunk(doc, "\n\n".join(current), breadcrumb, section_type)
            )

        return chunks if chunks else [self._make_chunk(doc, text, base_breadcrumb, section_type)]

    @staticmethod
    def _update_ancestors(
        ancestors: list[HierarchyNode], node: HierarchyNode
    ) -> list[HierarchyNode]:
        """Keep ancestors at lower hierarchy depth than the new node."""
        order = [
            "libro", "titulo", "capitulo", "seccion",
            "articulo", "apartado", "considerando", "anexo",
        ]
        level_idx = order.index(node.level)
        trimmed = [a for a in ancestors if order.index(a.level) < level_idx]
        return [*trimmed, node]
