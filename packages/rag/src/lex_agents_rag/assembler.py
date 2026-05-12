"""Context assembler — formats ranked chunks into a [REF:n]-annotated context string."""

from __future__ import annotations

import structlog
from lex_agents_shared.types import CitationMapping
from pydantic import BaseModel

from lex_agents_rag.retriever import RankedChunk

logger: structlog.BoundLogger = structlog.get_logger(__name__)

try:
    from lex_agents_shared.observability import get_observer as _get_lf_observer
except ImportError:
    _get_lf_observer = None  # type: ignore[assignment]


class AssembledContext(BaseModel):
    context_text: str
    citation_mapping: list[CitationMapping]


class ContextAssembler:
    """Assembles ranked chunks into a context block with [REF:n] markers.

    Each chunk becomes one citation: ``[REF:n]\\n<breadcrumb>\\n<text>\\n\\n``
    Indices start at 1 and are sequential.
    """

    def assemble(self, chunks: list[RankedChunk]) -> AssembledContext:
        parts: list[str] = []
        mappings: list[CitationMapping] = []

        for n, chunk in enumerate(chunks, start=1):
            breadcrumb = chunk.metadata.get("hierarchy_path", chunk.source_label)
            text_block = chunk.context_text + "\n\n" + chunk.text if chunk.context_text else chunk.text

            parts.append(f"[REF:{n}]\n{breadcrumb}\n{text_block}")

            mappings.append(
                CitationMapping(
                    index=n,
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.metadata.get("source_id", ""),
                    hierarchy_path=breadcrumb,
                    fragment_text=chunk.text[:500],
                )
            )

        context_text = "\n\n".join(parts)
        logger.debug("context_assembled", n_chunks=len(chunks), context_len=len(context_text))

        if _get_lf_observer is not None:
            _lf = _get_lf_observer()
            sources = list({m.source_id for m in mappings})
            span = _lf.start_span(
                "rag.context_assemble",
                input={"n_chunks": len(chunks)},
                metadata={"sources": sources, "context_len": len(context_text)},
            )
            _lf.end_span(span, output={"n_citations": len(mappings), "sources": sources})

        return AssembledContext(context_text=context_text, citation_mapping=mappings)
