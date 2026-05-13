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
        batch_size: int = 8,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._model: object | None = None  # lazy load

    def _load_model(self) -> object:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            logger.info("bge_m3_loading", model=self._model_name)
            model = SentenceTransformer(
                self._model_name,
                trust_remote_code=True,  # type: ignore[call-arg]
            )
            # BGE-M3 supports up to 8192 tokens but allocating attention
            # matrices at full length with any meaningful batch size exhausts
            # memory on commodity hardware.  512 tokens captures the relevant
            # chunk context for retrieval while staying well within limits.
            model.max_seq_length = 512
            self._model = model
            logger.info("bge_m3_loaded", model=self._model_name)
        return self._model

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Embed a batch of texts, returning dense + sparse for each.

        sentence-transformers ≥ 5.x dropped kwargs forwarding; BGE-M3 via
        SentenceTransformer.encode() returns only dense vectors. Sparse
        is left empty — retriever falls back to dense-only RRF.
        """
        if not texts:
            return []

        model = self._load_model()
        results: list[EmbeddingResult] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            outputs = model.encode(  # type: ignore[union-attr]
                batch,
                batch_size=self._batch_size,
                normalize_embeddings=True,
            )

            # ST 5.x returns ndarray (dense only); older versions returned dict
            import numpy as np

            if isinstance(outputs, dict):
                dense_vecs: list[list[float]] = outputs["dense_vecs"].tolist()
                lexical_weights: list[dict[int, float]] = outputs.get(
                    "lexical_weights", [{}] * len(batch)
                )
            else:
                arr = outputs if isinstance(outputs, np.ndarray) else np.array(outputs)
                dense_vecs = arr.tolist()
                lexical_weights = [{} for _ in batch]

            for dense, sparse in zip(dense_vecs, lexical_weights):
                results.append(EmbeddingResult(dense=dense, sparse=sparse))

        logger.debug("embedded_batch", n=len(texts))
        return results
