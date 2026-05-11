"""BGE-M3 embedder — dense (1024-dim) + sparse (SPLADE-style) in one pass."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)


@dataclass
class EmbeddingResult:
    dense: list[float]
    sparse: dict[int, float] = field(default_factory=dict)


class BgeM3Embedder:
    """Lazy-loaded BGE-M3 embedder that produces dense + sparse vectors.

    Uses sentence_transformers with the BGE-M3 model which natively provides
    both colbert/dense and sparse (lexical_weights) outputs in a single forward
    pass — no separate BM25 library needed.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 32,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._model: object | None = None  # lazy load

    def _load_model(self) -> object:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            logger.info("bge_m3_loading", model=self._model_name)
            self._model = SentenceTransformer(
                self._model_name,
                trust_remote_code=True,  # type: ignore[call-arg]
            )
            logger.info("bge_m3_loaded", model=self._model_name)
        return self._model

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts, returning dense + sparse for each."""
        if not texts:
            return []

        model = self._load_model()
        results: list[EmbeddingResult] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            outputs = model.encode(  # type: ignore[union-attr]
                batch,
                batch_size=len(batch),
                return_dense=True,
                return_sparse=True,
                normalize_embeddings=True,
            )

            dense_vecs: list[list[float]] = outputs["dense_vecs"].tolist()  # type: ignore[index]
            lexical_weights: list[dict[int, float]] = outputs.get(  # type: ignore[index,assignment]
                "lexical_weights", [{}] * len(batch)
            )

            for dense, sparse in zip(dense_vecs, lexical_weights):
                results.append(EmbeddingResult(dense=dense, sparse=sparse))

        logger.debug("embedded_batch", n=len(texts))
        return results
