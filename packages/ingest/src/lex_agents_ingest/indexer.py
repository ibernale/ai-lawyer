"""Qdrant indexer — upserts chunks with named dense + sparse vectors."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from lex_agents_ingest.canonical import Chunk
from lex_agents_ingest.embedder import EmbeddingResult

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DENSE_VECTOR = "dense"
_SPARSE_VECTOR = "sparse"
_DENSE_DIM = 1024


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


class QdrantIndexer:
    """Upsert legal chunks into Qdrant with dense + sparse named vectors."""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        collection_name: str = "lex_legal_docs",
    ) -> None:
        self._client = qdrant_client
        self._collection = collection_name

    def ensure_collection(self) -> None:
        """Create the collection if it does not exist."""
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            logger.debug("collection_exists", collection=self._collection)
            return

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config={
                _DENSE_VECTOR: VectorParams(
                    size=_DENSE_DIM,
                    distance=Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                _SPARSE_VECTOR: SparseVectorParams(
                    index=SparseIndexParams(),
                ),
            },
        )
        logger.info("collection_created", collection=self._collection)

    def upsert_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[EmbeddingResult],
    ) -> UpsertResult:
        """Upsert chunks idempotent by chunk_id."""
        if not chunks:
            return UpsertResult()
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )

        points: list[PointStruct] = []
        for chunk, emb in zip(chunks, embeddings):
            payload = chunk.model_dump(
                exclude={"text", "context_text"},
                mode="json",
            )
            payload["text"] = chunk.text
            payload["context_text"] = chunk.context_text

            points.append(
                PointStruct(
                    id=self._chunk_id_to_uint(chunk.chunk_id),
                    vector={
                        _DENSE_VECTOR: emb.dense,
                        _SPARSE_VECTOR: SparseVector(
                            indices=list(emb.sparse.keys()),
                            values=list(emb.sparse.values()),
                        ),
                    },
                    payload=payload,
                )
            )

        self._client.upsert(
            collection_name=self._collection,
            points=points,
        )

        result = UpsertResult(inserted=len(points))
        logger.info(
            "chunks_upserted",
            collection=self._collection,
            n=len(points),
        )
        return result

    @staticmethod
    def _chunk_id_to_uint(chunk_id: str) -> int:
        """Derive a stable uint64 from a hex chunk_id (first 16 hex chars)."""
        return int(chunk_id[:16], 16)
