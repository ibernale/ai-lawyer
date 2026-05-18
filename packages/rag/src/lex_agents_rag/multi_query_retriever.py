"""MultiQueryRetriever — generates query paraphrases and fuses results via RRF.

Wraps HybridRetriever: generates N-1 Spanish paraphrases of the original query
via Claude Haiku, runs retrieval for each, then merges with Reciprocal Rank
Fusion.  Original query is always included as query #1.  Paraphrase generation
failures degrade gracefully to single-query retrieval.
"""

from __future__ import annotations

import structlog
from anthropic.types import TextBlock
from lex_agents_shared.anthropic_client import MODEL_HAIKU, AnthropicClientWrapper

from lex_agents_rag.retriever import HybridRetriever, RankedChunk, SearchFilters

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_RRF_K = 60  # constant k in RRF formula: 1 / (k + rank)


class MultiQueryRetriever:
    """Wraps :class:`HybridRetriever` with multi-query expansion via RRF.

    *n_queries* controls the total number of queries run (original +
    paraphrases).  Setting *n_queries=1* disables paraphrase generation and
    falls back to a plain single-query search.
    """

    def __init__(
        self,
        base_retriever: HybridRetriever,
        anthropic_client: AnthropicClientWrapper,
        n_queries: int = 3,
        model: str = MODEL_HAIKU,
    ) -> None:
        self._retriever = base_retriever
        self._client = anthropic_client
        self._n_queries = n_queries
        self._model = model

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        k: int = 30,
    ) -> list[RankedChunk]:
        """Run multi-query retrieval and return top-*k* fused results."""
        paraphrases = self._generate_paraphrases(query)
        all_queries = [query, *paraphrases]
        logger.info(
            "multi_query_retriever_search",
            n_queries=len(all_queries),
            paraphrases=paraphrases,
        )

        per_query_results: list[list[RankedChunk]] = []
        for q in all_queries:
            try:
                results = self._retriever.search(q, filters, k_rrf=k)
                per_query_results.append(results)
            except Exception:
                logger.exception("multi_query_retriever_search_error", query=q[:80])

        if not per_query_results:
            return []

        return self._fuse_with_rrf(per_query_results, k=k)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_paraphrases(self, query: str) -> list[str]:
        """Return up to *n_queries-1* Spanish paraphrases; ``[]`` on any failure."""
        n = self._n_queries - 1
        if n <= 0:
            return []

        prompt = (
            f"Genera {n} formulaciones alternativas de la siguiente consulta jurídica en español. "
            "Devuelve ÚNICAMENTE las consultas alternativas, una por línea, "
            "sin numeración ni explicaciones adicionales.\n\n"
            f"Consulta: {query}"
        )
        try:
            resp = self._client.messages_create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text_block = next((b for b in resp.content if isinstance(b, TextBlock)), None)
            raw = text_block.text.strip() if text_block else ""
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            paraphrases = lines[:n]
            logger.debug("multi_query_paraphrases_generated", n=len(paraphrases))
            return paraphrases
        except Exception:
            logger.warning("multi_query_paraphrases_failed", query=query[:80])
            return []

    def _fuse_with_rrf(
        self,
        results_per_query: list[list[RankedChunk]],
        k: int = 30,
    ) -> list[RankedChunk]:
        """Merge multiple ranked lists via RRF; return top-*k* de-duplicated chunks."""
        scores: dict[str, float] = {}
        best_chunk: dict[str, RankedChunk] = {}

        for result_list in results_per_query:
            for rank, chunk in enumerate(result_list, start=1):
                scores[chunk.chunk_id] = (
                    scores.get(chunk.chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
                )
                if chunk.chunk_id not in best_chunk or chunk.score > best_chunk[chunk.chunk_id].score:
                    best_chunk[chunk.chunk_id] = chunk

        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:k]
        merged: list[RankedChunk] = []
        for new_rank, cid in enumerate(sorted_ids, start=1):
            chunk = best_chunk[cid]
            merged.append(
                RankedChunk(
                    chunk_id=chunk.chunk_id,
                    score=scores[cid],
                    rank=new_rank,
                    metadata=chunk.metadata,
                    text=chunk.text,
                    context_text=chunk.context_text,
                    source_label=chunk.source_label,
                )
            )
        logger.info("multi_query_rrf_merged", n_merged=len(merged))
        return merged
