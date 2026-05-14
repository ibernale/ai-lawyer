"""Voyage AI embedder — dense 1024-dim vectors via API (no local model)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# voyage-multilingual-2: 1024-dim, supports ES/EU languages, $0.12/M tokens.
# Same dimension as the previous BGE-M3 model — existing Qdrant collections
# are compatible without recreation.
_DEFAULT_MODEL = "voyage-multilingual-2"
_EMBED_BATCH_SIZE = 128  # Voyage API limit per call


@dataclass
class EmbeddingResult:
    dense: list[float]
    sparse: dict[int, float] = field(default_factory=dict)


class VoyageEmbedder:
    """Voyage AI embedder that produces 1024-dim dense vectors via HTTP API.

    Replaces the local BGE-M3 / sentence-transformers implementation.
    No GPU, no model download — just API calls.  Sparse vectors remain empty;
    the HybridRetriever falls back to dense-only RRF automatically.

    Requires env var: VOYAGE_API_KEY
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        batch_size: int = _EMBED_BATCH_SIZE,
    ) -> None:
        self._model = model
        self._batch_size = batch_size
        self._client: object | None = None  # lazy init

    def _get_client(self) -> object:
        if self._client is None:
            import voyageai  # type: ignore[import-untyped]

            api_key = os.environ.get("VOYAGE_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "VOYAGE_API_KEY env var is not set. "
                    "Set it in Secrets Manager and restart the service."
                )
            self._client = voyageai.Client(api_key=api_key)
            logger.info("voyage_client_init", model=self._model)
        return self._client

    def embed_batch(
        self,
        texts: list[str],
        input_type: str = "document",
    ) -> list[EmbeddingResult]:
        """Embed a batch of texts, returning EmbeddingResult with dense vector.

        Args:
            texts: Texts to embed.
            input_type: "document" for indexing, "query" for retrieval queries.
                Voyage AI uses different representations for each.
        """
        if not texts:
            return []

        client = self._get_client()
        results: list[EmbeddingResult] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            response = client.embed(  # type: ignore[union-attr]
                batch,
                model=self._model,
                input_type=input_type,
            )
            for dense in response.embeddings:
                results.append(EmbeddingResult(dense=dense, sparse={}))

            logger.debug("voyage_embedded_batch", n=len(batch), model=self._model)

        return results

    def embed_query(self, query: str) -> EmbeddingResult:
        """Convenience wrapper for single query embedding (uses input_type='query')."""
        results = self.embed_batch([query], input_type="query")
        return results[0]


# Backwards-compatible alias — existing code that imports BgeM3Embedder still works.
BgeM3Embedder = VoyageEmbedder
