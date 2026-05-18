"""CRAGFilter — Contextual Relevance-Aware Grading filter (Fase 11B.3).

Single batch LLM call classifies each retrieved chunk as:
  R = Relevant   — keep
  I = Irrelevant — discard
  U = Uncertain  — keep (borderline; better over- than under-include)

Two guard-rails prevent context starvation:
  _MIN_CHUNKS_TO_FILTER   — skip filtering entirely when input is this small
                            (saves an LLM call on sparse result sets).
  _MIN_CHUNKS_AFTER_FILTER — if fewer chunks survive the filter, fall back to
                             the top N by original rank rather than leaving the
                             pipeline with almost no context.
"""

from __future__ import annotations

import re

import structlog
from anthropic.types import TextBlock
from lex_agents_shared.anthropic_client import MODEL_HAIKU, AnthropicClientWrapper

from lex_agents_rag.retriever import RankedChunk

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MIN_CHUNKS_TO_FILTER = 5    # skip if input ≤ this many chunks
_MIN_CHUNKS_AFTER_FILTER = 3  # fallback threshold after filtering


class CRAGFilter:
    """LLM-based relevance filter applied after initial retrieval.

    Reduces noise from borderline chunks without risking context starvation.
    All failures (LLM timeout, parse errors) degrade gracefully — the
    original chunk list is returned unchanged so the pipeline keeps running.
    """

    def __init__(
        self,
        anthropic_client: AnthropicClientWrapper,
        model: str = MODEL_HAIKU,
        relevance_threshold: float = 0.3,  # reserved for future scoring mode
    ) -> None:
        self._client = anthropic_client
        self._model = model

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def filter(
        self,
        query: str,
        chunks: list[RankedChunk],
        max_to_keep: int = 20,
    ) -> list[RankedChunk]:
        """Return filtered list; never raises — falls back gracefully on errors."""
        if len(chunks) <= _MIN_CHUNKS_TO_FILTER:
            logger.debug("crag_filter_skipped", n_chunks=len(chunks))
            return chunks[:max_to_keep]

        chunks_to_classify = chunks[:max_to_keep]
        classifications = self._classify(query, chunks_to_classify)

        if not classifications:
            # LLM call failed — return original list unchanged
            logger.warning("crag_filter_fallback_llm_error", n_chunks=len(chunks_to_classify))
            return chunks_to_classify

        relevant = [
            c for c, label in zip(chunks_to_classify, classifications) if label != "I"
        ]
        logger.info(
            "crag_filter_applied",
            total=len(chunks_to_classify),
            relevant=len(relevant),
            irrelevant=len(chunks_to_classify) - len(relevant),
        )

        if len(relevant) < _MIN_CHUNKS_AFTER_FILTER:
            # Too aggressive — return top N by original rank as fallback
            logger.info("crag_filter_fallback_too_few", surviving=len(relevant))
            return sorted(chunks_to_classify, key=lambda c: c.rank)[:_MIN_CHUNKS_AFTER_FILTER]

        return relevant

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify(self, query: str, chunks: list[RankedChunk]) -> list[str]:
        """Return R/I/U labels (one per chunk). Returns ``[]`` on any error."""
        numbered = "\n\n".join(
            f"{i + 1}: {chunk.text[:400]}" for i, chunk in enumerate(chunks)
        )
        prompt = (
            "Clasifica cada fragmento numerado según su relevancia para la consulta.\n"
            "Responde ÚNICAMENTE con líneas en el formato: N: X\n"
            "donde X es R (Relevante), I (Irrelevante) o U (Incierto).\n\n"
            f"Consulta: {query}\n\n"
            f"Fragmentos:\n{numbered}"
        )
        try:
            resp = self._client.messages_create(
                model=self._model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text_block = next((b for b in resp.content if isinstance(b, TextBlock)), None)
            raw = text_block.text.strip() if text_block else ""
            return self._parse_classifications(raw, len(chunks))
        except Exception:
            logger.exception("crag_filter_classify_error")
            return []

    @staticmethod
    def _parse_classifications(raw: str, expected: int) -> list[str]:
        """Parse ``N: X`` lines into a label list, padded to *expected* length.

        Missing entries default to ``'U'`` (uncertain = keep).
        """
        pattern = re.compile(r"^\s*(\d+)\s*:\s*([RIUriu])\s*$")
        result: dict[int, str] = {}
        for line in raw.splitlines():
            m = pattern.match(line)
            if m:
                result[int(m.group(1))] = m.group(2).upper()
        return [result.get(i + 1, "U") for i in range(expected)]
