"""Cross-encoder reranker with passthrough fallback for test environments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog
from pydantic import BaseModel

from lex_agents_rag.retriever import RankedChunk

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class RerankerConfig(BaseModel):
    model: str = "BAAI/bge-reranker-v2-m3"
    top_k: int = 10
    enabled: bool = True


class BaseReranker(ABC):
    @abstractmethod
    def rerank(self, query: str, chunks: list[RankedChunk], top_k: int = 10) -> list[RankedChunk]:
        ...


class PassthroughReranker(BaseReranker):
    """No-op reranker — returns chunks unchanged, trimmed to top_k."""

    def rerank(
        self, query: str, chunks: list[RankedChunk], top_k: int = 10
    ) -> list[RankedChunk]:
        return chunks[:top_k]


class CrossEncoderReranker(BaseReranker):
    """BGE reranker-v2-m3 cross-encoder, lazy-loaded."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("reranker_loading", model=self._model_name)
            self._model = CrossEncoder(self._model_name, trust_remote_code=True)
            logger.info("reranker_loaded", model=self._model_name)
        return self._model

    def rerank(
        self, query: str, chunks: list[RankedChunk], top_k: int = 10
    ) -> list[RankedChunk]:
        if not chunks:
            return []

        model = self._load_model()
        pairs = [(query, c.text) for c in chunks]
        scores: list[float] = model.predict(pairs).tolist()

        ranked = sorted(
            zip(scores, chunks), key=lambda x: x[0], reverse=True
        )
        result = []
        for new_rank, (score, chunk) in enumerate(ranked[:top_k], start=1):
            result.append(chunk.model_copy(update={"score": float(score), "rank": new_rank}))

        logger.debug("reranked", n_input=len(chunks), n_output=len(result))
        return result


def make_reranker(config: RerankerConfig) -> BaseReranker:
    """Factory — returns PassthroughReranker if disabled."""
    if not config.enabled:
        return PassthroughReranker()
    return CrossEncoderReranker(model_name=config.model)
