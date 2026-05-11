"""Hybrid retriever — dense + sparse search fused with Reciprocal Rank Fusion."""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from lex_agents_ingest.embedder import BgeM3Embedder
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, Range, SparseVector

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"


class RankedChunk(BaseModel):
    chunk_id: str
    score: float
    rank: int
    metadata: dict[str, Any]
    text: str
    context_text: str
    source_label: str


class SearchFilters(BaseModel):
    jurisdiction: str | None = None
    status: str | None = None
    in_force_at: date | None = None
    source_ids: list[str] | None = None
    document_type: str | None = None


class HybridRetriever:
    """Dense + sparse hybrid search with RRF merging.

    Args:
        qdrant_client: Connected QdrantClient.
        embedder: BgeM3Embedder for query embedding.
        collection: Qdrant collection name.
    """

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedder: BgeM3Embedder,
        collection: str = "lex_legal_docs",
    ) -> None:
        self._client = qdrant_client
        self._embedder = embedder
        self._collection = collection

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        k_dense: int = 50,
        k_sparse: int = 50,
        k_rrf: int = 30,
    ) -> list[RankedChunk]:
        """Run hybrid search and return the top *k_rrf* merged results."""
        embeddings = self._embedder.embed_batch([query])
        emb = embeddings[0]

        qdrant_filter = self._build_filter(filters) if filters else None

        dense_hits = self._client.query_points(
            collection_name=self._collection,
            query=emb.dense,
            using=_DENSE_VECTOR,
            limit=k_dense,
            query_filter=qdrant_filter,
            with_payload=True,
        ).points

        sparse_hits: list[Any] = []
        if emb.sparse:
            sparse_hits = self._client.query_points(
                collection_name=self._collection,
                query=SparseVector(
                    indices=list(emb.sparse.keys()),
                    values=list(emb.sparse.values()),
                ),
                using=_SPARSE_VECTOR,
                limit=k_sparse,
                query_filter=qdrant_filter,
                with_payload=True,
            ).points

        merged = self._rrf(list(dense_hits), list(sparse_hits))
        top = merged[:k_rrf]

        logger.debug(
            "hybrid_search",
            query_len=len(query),
            dense_hits=len(dense_hits),
            sparse_hits=len(sparse_hits),
            merged=len(top),
        )
        return top

    # ------------------------------------------------------------------
    # RRF
    # ------------------------------------------------------------------

    def _rrf(
        self,
        dense: list[Any],
        sparse: list[Any],
        k: int = 60,
    ) -> list[RankedChunk]:
        """Reciprocal Rank Fusion: score = Σ 1/(k + rank)."""
        scores: dict[str, float] = {}
        payloads: dict[str, Any] = {}

        for rank, hit in enumerate(dense, start=1):
            cid = str(hit.payload.get("chunk_id", str(hit.id)))
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            payloads[cid] = hit.payload

        for rank, hit in enumerate(sparse, start=1):
            cid = str(hit.payload.get("chunk_id", str(hit.id)))
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in payloads:
                payloads[cid] = hit.payload

        sorted_ids = sorted(scores, key=lambda c: scores[c], reverse=True)
        results: list[RankedChunk] = []
        for rank, cid in enumerate(sorted_ids, start=1):
            payload = payloads[cid]
            results.append(
                RankedChunk(
                    chunk_id=cid,
                    score=scores[cid],
                    rank=rank,
                    metadata=payload,
                    text=payload.get("text", ""),
                    context_text=payload.get("context_text", ""),
                    source_label=self._format_source_label(payload),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Filter builder
    # ------------------------------------------------------------------

    def _build_filter(self, filters: SearchFilters) -> Filter:
        conditions = []

        if filters.jurisdiction:
            conditions.append(
                FieldCondition(key="jurisdiction", match=MatchValue(value=filters.jurisdiction))
            )
        if filters.status:
            conditions.append(
                FieldCondition(key="status", match=MatchValue(value=filters.status))
            )
        if filters.in_force_at:
            conditions.append(
                FieldCondition(
                    key="entry_into_force",
                    range=Range(lte=filters.in_force_at.isoformat()),
                )
            )
        if filters.document_type:
            conditions.append(
                FieldCondition(
                    key="document_type", match=MatchValue(value=filters.document_type)
                )
            )

        return Filter(must=conditions) if conditions else Filter()

    @staticmethod
    def _format_source_label(payload: dict[str, Any]) -> str:
        source_id = payload.get("source_id", "")
        path = payload.get("hierarchy_path", "")
        return f"{source_id} — {path}" if path else source_id
