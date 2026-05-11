"""Contextual Retrieval enrichment — adds a 50-100 word context to each chunk."""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog
from anthropic import Anthropic
from anthropic.types import MessageParam

from lex_agents_ingest.canonical import CanonicalDocument, Chunk
from lex_agents_shared.anthropic_client import MODEL_HAIKU

logger: structlog.BoundLogger = structlog.get_logger(__name__)

CONTEXT_SYSTEM_PROMPT = """\
Eres un asistente jurídico especializado en normativa bancaria europea y española. \
Tu tarea es generar un breve párrafo de contexto (50-100 palabras) que sitúe el \
fragmento de texto proporcionado dentro del documento normativo completo que se \
adjunta. El contexto debe indicar qué regula el fragmento, su posición en la \
estructura normativa y su relación con los preceptos más relevantes del documento. \
Responde ÚNICAMENTE con el párrafo de contexto, sin encabezados ni aclaraciones.\
"""


class Contextualizer:
    """Enrich chunks with a contextual summary using claude-haiku with prompt caching.

    Uses Anthropic's Contextual Retrieval approach:
    - System message = full document text (cached with cache_control: ephemeral)
    - User message = individual chunk text
    - Model: claude-haiku to minimise cost
    """

    def __init__(
        self,
        anthropic_client: Anthropic,
        cache_dir: str | Path = "data/contexts",
    ) -> None:
        self._client = anthropic_client
        self._cache_dir = Path(cache_dir)

    def enrich(self, doc: CanonicalDocument, chunks: list[Chunk]) -> list[Chunk]:
        """Return a new list of chunks with `context_text` populated."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        enriched: list[Chunk] = []
        first_call = True

        for chunk in chunks:
            context = self._get_context(doc, chunk, log_cache_miss=first_call)
            first_call = False
            enriched.append(chunk.model_copy(update={"context_text": context}))

        return enriched

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cache_key(self, doc: CanonicalDocument, chunk: Chunk) -> str:
        raw = f"{doc.source_id}::{chunk.chunk_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, doc: CanonicalDocument, chunk: Chunk) -> Path:
        return self._cache_dir / f"{self._cache_key(doc, chunk)}.txt"

    def _get_context(
        self,
        doc: CanonicalDocument,
        chunk: Chunk,
        log_cache_miss: bool = False,
    ) -> str:
        path = self._cache_path(doc, chunk)
        if path.exists():
            logger.debug("context_cache_hit", chunk_id=chunk.chunk_id)
            return path.read_text(encoding="utf-8")

        context = self._call_api(doc, chunk, log_cache_miss=log_cache_miss)
        path.write_text(context, encoding="utf-8")
        return context

    def _call_api(
        self,
        doc: CanonicalDocument,
        chunk: Chunk,
        log_cache_miss: bool = False,
    ) -> str:
        system: list[MessageParam] = []  # type: ignore[assignment]

        # Build system content with prompt caching on the full document
        # The ephemeral cache_control on a block ≥ 1024 tokens activates prompt caching.
        system_content = [
            {
                "type": "text",
                "text": CONTEXT_SYSTEM_PROMPT,
            },
            {
                "type": "text",
                "text": f"<document>\n{doc.full_text}\n</document>",
                "cache_control": {"type": "ephemeral"},
            },
        ]

        response = self._client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=256,
            temperature=0,  # type: ignore[arg-type]
            system=system_content,  # type: ignore[arg-type]
            messages=[
                {
                    "role": "user",
                    "content": f"Chunk:\n\n{chunk.text}",
                }
            ],
        )

        usage = response.usage
        if log_cache_miss and hasattr(usage, "cache_read_input_tokens"):
            if usage.cache_read_input_tokens == 0:  # type: ignore[union-attr]
                logger.warning(
                    "prompt_cache_miss",
                    source_id=doc.source_id,
                    chunk_id=chunk.chunk_id,
                )
            else:
                logger.debug(
                    "prompt_cache_hit",
                    source_id=doc.source_id,
                    cache_read_tokens=usage.cache_read_input_tokens,  # type: ignore[union-attr]
                )

        context = response.content[0].text  # type: ignore[union-attr]
        logger.debug(
            "context_generated",
            source_id=doc.source_id,
            chunk_id=chunk.chunk_id,
            context_len=len(context),
        )
        return context
