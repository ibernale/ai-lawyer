"""Multi-Query Retrieval — genera N paráfrasis de la query y fusiona con RRF."""

from __future__ import annotations

from typing import Any

import structlog
from lex_agents_shared.anthropic_client import MODEL_HAIKU

from lex_agents_rag.retriever import HybridRetriever, RankedChunk, SearchFilters

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_PARAPHRASE_SYSTEM = (
    "Genera {n} formulaciones alternativas de la siguiente pregunta jurídica. "
    "Una por línea. Solo las preguntas, sin numeración ni explicación."
)

_RRF_K = 60


def _rrf_score(rank: int, k: int = _RRF_K) -> float:
    """Reciprocal Rank Fusion score: 1 / (k + rank)."""
    return 1.0 / (k + rank)


def _fuse_with_rrf(result_lists: list[list[RankedChunk]]) -> list[RankedChunk]:
    """Merge N ranked lists into one using Reciprocal Rank Fusion.

    Each chunk is identified by its ``chunk_id``.  Scores are accumulated
    across all lists.  Duplicate chunks are collapsed, keeping the metadata
    from the appearance with the highest per-position RRF score.

    Args:
        result_lists: One list per query, each already sorted by relevance.

    Returns:
        Deduplicated list sorted by accumulated RRF score (descending).
        Each returned :class:`RankedChunk` carries the accumulated score and
        a new ``rank`` reflecting its final position.
    """
    accumulated_scores: dict[str, float] = {}
    best_chunk: dict[str, RankedChunk] = {}

    for ranked_list in result_lists:
        for rank, chunk in enumerate(ranked_list, start=1):
            score = _rrf_score(rank)
            accumulated_scores[chunk.chunk_id] = (
                accumulated_scores.get(chunk.chunk_id, 0.0) + score
            )
            # Keep the chunk object from the list position with highest score
            prev_best = best_chunk.get(chunk.chunk_id)
            if prev_best is None or score > prev_best.score:
                best_chunk[chunk.chunk_id] = chunk

    sorted_ids = sorted(
        accumulated_scores, key=lambda cid: accumulated_scores[cid], reverse=True
    )

    results: list[RankedChunk] = []
    for new_rank, cid in enumerate(sorted_ids, start=1):
        chunk = best_chunk[cid]
        results.append(
            RankedChunk(
                chunk_id=chunk.chunk_id,
                score=accumulated_scores[cid],
                rank=new_rank,
                metadata=chunk.metadata,
                text=chunk.text,
                context_text=chunk.context_text,
                source_label=chunk.source_label,
            )
        )

    return results


class MultiQueryRetriever:
    """Retriever that generates N query paraphrases and merges results via RRF.

    For each paraphrase (plus the original query), ``HybridRetriever.search``
    is called.  All result lists are then fused with Reciprocal Rank Fusion so
    that chunks appearing high in multiple lists bubble up to the top.

    Args:
        base_retriever: Configured :class:`HybridRetriever` to delegate to.
        anthropic_client: Synchronous ``anthropic.Anthropic`` client.
        n_queries: Number of paraphrase queries to generate (default 3).
        model: Claude model used for paraphrase generation (default Haiku).
    """

    def __init__(
        self,
        base_retriever: HybridRetriever,
        anthropic_client: Any,
        n_queries: int = 3,
        model: str = MODEL_HAIKU,
    ) -> None:
        self._retriever = base_retriever
        self._client = anthropic_client
        self._n_queries = n_queries
        self._model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        k: int = 30,
    ) -> list[RankedChunk]:
        """Search with multi-query expansion and RRF fusion.

        Steps:
        1. Generate ``n_queries`` paraphrases of *query* via Claude.
        2. Run ``base_retriever.search`` for the original + each paraphrase.
        3. Fuse all result lists with Reciprocal Rank Fusion.
        4. Return the top *k* deduplicated chunks.

        Falls back to a plain ``base_retriever.search`` call if Claude fails.

        Args:
            query: Original user query.
            filters: Optional metadata filters forwarded to the base retriever.
            k: Maximum number of chunks to return.

        Returns:
            Deduplicated, RRF-ranked list of at most *k* :class:`RankedChunk`.
        """
        paraphrases = self._generate_paraphrases(query)
        all_queries = [query, *paraphrases]

        all_result_lists: list[list[RankedChunk]] = []
        for q in all_queries:
            results = self._retriever.search(q, filters=filters, k_rrf=k)
            all_result_lists.append(results)

        merged = self._fuse_with_rrf(all_result_lists)
        top = merged[:k]

        logger.debug(
            "multi_query_search",
            n_queries=len(all_queries),
            total_before_dedup=sum(len(r) for r in all_result_lists),
            after_dedup=len(merged),
            returned=len(top),
        )
        return top

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _generate_paraphrases(self, query: str) -> list[str]:
        """Ask Claude to generate ``n_queries`` paraphrases of *query*.

        Returns an empty list (with a warning log) if the API call fails.
        """
        system = _PARAPHRASE_SYSTEM.format(n=self._n_queries)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                temperature=0.7,
                system=system,
                messages=[{"role": "user", "content": query}],
            )
            raw: str = response.content[0].text.strip()
            paraphrases = [line.strip() for line in raw.split("\n") if line.strip()]
            logger.debug(
                "paraphrases_generated",
                original=query[:80],
                n=len(paraphrases),
            )
            return paraphrases
        except Exception:
            logger.warning(
                "paraphrase_generation_failed",
                query=query[:80],
                exc_info=True,
            )
            return []

    def _fuse_with_rrf(self, result_lists: list[list[RankedChunk]]) -> list[RankedChunk]:
        """Merge N ranked lists into one using Reciprocal Rank Fusion.

        Delegates to the module-level :func:`_fuse_with_rrf` helper.
        """
        return _fuse_with_rrf(result_lists)
