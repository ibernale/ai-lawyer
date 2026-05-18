"""CRAG — Corrective RAG: filtro post-retrieval de relevancia."""

from __future__ import annotations

import re
from typing import Any

import structlog
from lex_agents_shared.anthropic_client import MODEL_HAIKU

from lex_agents_rag.retriever import RankedChunk

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MIN_CHUNKS_TO_FILTER = 5   # skip CRAG entirely when ≤ this many chunks
_MIN_CHUNKS_AFTER_FILTER = 3  # fallback if fewer than this survive
_CHUNK_TEXT_LIMIT = 300

_RELEVANCE_SYSTEM = (
    "Eres un evaluador de relevancia jurídica. "
    "Para cada fragmento numerado, responde SOLO con el número y una letra: "
    "R (relevante), I (irrelevante), U (incierto). "
    "Una por línea. Ejemplo: '1:R\\n2:I\\n3:U'"
)

# Matches lines like "1:R", "12:I", "3:U" (case-insensitive)
_CLASSIFICATION_RE = re.compile(r"^\s*(\d+)\s*:\s*([RIUriu])\s*$")


def _parse_classifications(raw: str) -> dict[int, str]:
    """Parse Claude's line-by-line classification response.

    Lines that don't match the expected ``N:X`` pattern are silently
    ignored so partial responses still produce useful output.

    Args:
        raw: Raw text from the LLM response, e.g. ``"1:R\\n2:I\\n3:U"``.

    Returns:
        Mapping of 1-based index → uppercase classification letter (R/I/U).
    """
    result: dict[int, str] = {}
    for line in raw.splitlines():
        m = _CLASSIFICATION_RE.match(line)
        if m:
            idx = int(m.group(1))
            label = m.group(2).upper()
            result[idx] = label
    return result


class CRAGFilter:
    """Post-retrieval relevance filter (Corrective RAG).

    Evaluates all retrieved chunks in a **single** LLM call and discards
    those classified as irrelevant.  Falls back gracefully to the original
    chunk list when Claude is unavailable or the filter is too aggressive.

    Args:
        anthropic_client: Synchronous ``anthropic.Anthropic`` client.
        model: Claude model used for relevance classification (default Haiku).
        relevance_threshold: Unused for classification-based filtering; kept
            for API compatibility with future score-based variants.
    """

    def __init__(
        self,
        anthropic_client: Any,
        model: str = MODEL_HAIKU,
        relevance_threshold: float = 0.3,
    ) -> None:
        self._client = anthropic_client
        self._model = model
        self._relevance_threshold = relevance_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter(
        self,
        query: str,
        chunks: list[RankedChunk],
        max_to_keep: int = 20,
    ) -> list[RankedChunk]:
        """Filter irrelevant chunks from *chunks* using a single LLM call.

        Steps:
        1. If there are ≤ 5 chunks, return them all (not worth the latency).
        2. Ask Claude to classify each chunk as R/I/U in one batch request.
        3. Discard chunks classified as "I".
        4. If fewer than 5 chunks survive, return the original top-5 instead.
        5. Return the surviving chunks (up to *max_to_keep*), preserving order.

        Falls back to the original chunks if Claude raises an exception.

        Args:
            query: The user query chunks were retrieved for.
            chunks: Ordered list of retrieved chunks (e.g. from RRF).
            max_to_keep: Hard cap on the number of chunks returned.

        Returns:
            Filtered (and capped) list of :class:`RankedChunk`.
        """
        if len(chunks) <= _MIN_CHUNKS_TO_FILTER:
            return chunks

        classifications = self._classify_chunks(query, chunks)
        if classifications is None:
            # Claude failed — return originals unchanged
            return chunks[:max_to_keep]

        kept = [
            chunk
            for i, chunk in enumerate(chunks)
            if classifications.get(i + 1, "U") != "I"
        ]

        n_filtered = len(chunks) - len(kept)
        logger.info(
            "crag_filter",
            total=len(chunks),
            kept=len(kept),
            filtered=n_filtered,
        )

        if len(kept) < _MIN_CHUNKS_AFTER_FILTER:
            logger.warning(
                "crag_filter_too_aggressive",
                kept=len(kept),
                fallback_n=_MIN_CHUNKS_AFTER_FILTER,
            )
            return chunks[:_MIN_CHUNKS_AFTER_FILTER]

        return kept[:max_to_keep]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _classify_chunks(
        self, query: str, chunks: list[RankedChunk]
    ) -> dict[int, str] | None:
        """Ask Claude to classify every chunk in a single batch prompt.

        Args:
            query: The user query.
            chunks: Chunks to evaluate.

        Returns:
            Mapping of 1-based chunk index → classification letter (R/I/U),
            or ``None`` if the API call fails.
        """
        chunk_lines = "\n\n".join(
            f"[{i + 1}] {chunk.text[:_CHUNK_TEXT_LIMIT]}"
            for i, chunk in enumerate(chunks)
        )
        user_message = f"Query: {query}\n\n{chunk_lines}"

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=256,
                temperature=0,
                system=_RELEVANCE_SYSTEM,
                messages=[{"role": "user", "content": user_message}],
            )
            raw: str = response.content[0].text.strip()
            return _parse_classifications(raw)
        except Exception:
            logger.warning("crag_classification_failed", exc_info=True)
            return None
