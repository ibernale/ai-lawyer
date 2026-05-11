"""RAG endpoints — /api/v1/rag/search and /api/v1/rag/answer."""

from __future__ import annotations

import importlib.resources
from functools import lru_cache
from typing import Any

import structlog
from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient

from lex_agents_ingest.embedder import BgeM3Embedder
from lex_agents_ingest.indexer import QdrantIndexer
from lex_agents_rag.assembler import ContextAssembler
from lex_agents_rag.query_rewriter import LegalQueryRewriter
from lex_agents_rag.reranker import RerankerConfig, make_reranker
from lex_agents_rag.retriever import HybridRetriever, SearchFilters
from lex_agents_shared.anthropic_client import MODEL_OPUS
from lex_agents_shared.types import CitationMapping

from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

_RAG_PROMPT_VERSION = "1"

# ---------------------------------------------------------------------------
# Dependency factories (cached per process)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_embedder(model: str) -> BgeM3Embedder:
    return BgeM3Embedder(model_name=model)


@lru_cache(maxsize=1)
def _get_qdrant(url: str, api_key: str) -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key or None)


def _get_retriever(settings: Settings = Depends(get_settings)) -> HybridRetriever:
    embedder = _get_embedder(settings.embedder_model)
    client = _get_qdrant(settings.qdrant_url, settings.qdrant_api_key.get_secret_value())
    return HybridRetriever(
        qdrant_client=client,
        embedder=embedder,
        collection=settings.qdrant_collection,
    )


def _get_reranker(settings: Settings = Depends(get_settings)) -> Any:
    cfg = RerankerConfig(
        model=settings.reranker_model,
        top_k=settings.rag_top_k,
        enabled=settings.reranker_enabled,
    )
    return make_reranker(cfg)


def _get_query_rewriter(settings: Settings = Depends(get_settings)) -> LegalQueryRewriter:
    client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    return LegalQueryRewriter(anthropic_client=client)


def _load_rag_prompt() -> str:
    try:
        path = importlib.resources.files("lex_agents_api") / "prompts" / "rag_plain_v1.txt"
        return path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        return _FALLBACK_PROMPT


_FALLBACK_PROMPT = """\
Eres un asistente jurídico especializado en normativa bancaria europea y española. \
Responde ÚNICAMENTE basándote en los fragmentos normativos proporcionados, citando \
cada afirmación con [REF:n]. Si no dispones de fundamento normativo suficiente, \
decláralo explícitamente. Al final incluye el aviso: \
"Este análisis tiene carácter meramente informativo y no sustituye el asesoramiento \
jurídico profesional."
"""


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    filters: dict[str, Any] | None = None
    top_k: int = 10


class SearchResult(BaseModel):
    chunk_id: str
    score: float
    hierarchy_path: str
    source_label: str
    fragment: str
    context_summary: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query_rewritten: str


class AnswerRequest(BaseModel):
    query: str
    filters: dict[str, Any] | None = None


class AnswerResponse(BaseModel):
    answer: str
    citations: list[CitationMapping]
    query_rewritten: str
    model_used: str
    prompt_version: str
    verification_status: str = "pending"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponse)
def search(
    req: SearchRequest,
    retriever: HybridRetriever = Depends(_get_retriever),
    reranker: Any = Depends(_get_reranker),
    query_rewriter: LegalQueryRewriter = Depends(_get_query_rewriter),
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    rewritten = query_rewriter.rewrite(req.query)
    sf = _parse_filters(req.filters)

    top_k = req.top_k or settings.rag_top_k
    raw_chunks = retriever.search(rewritten.expanded_query, filters=sf, k_rrf=top_k * 3)
    ranked = reranker.rerank(rewritten.expanded_query, raw_chunks, top_k=top_k)

    results = [
        SearchResult(
            chunk_id=c.chunk_id,
            score=c.score,
            hierarchy_path=c.metadata.get("hierarchy_path", ""),
            source_label=c.source_label,
            fragment=c.text[:200],
            context_summary=c.context_text[:200] if c.context_text else "",
        )
        for c in ranked
    ]
    return SearchResponse(results=results, query_rewritten=rewritten.expanded_query)


@router.post("/answer", response_model=AnswerResponse)
def answer(
    req: AnswerRequest,
    retriever: HybridRetriever = Depends(_get_retriever),
    reranker: Any = Depends(_get_reranker),
    query_rewriter: LegalQueryRewriter = Depends(_get_query_rewriter),
    settings: Settings = Depends(get_settings),
) -> AnswerResponse:
    rewritten = query_rewriter.rewrite(req.query)
    sf = _parse_filters(req.filters)

    raw_chunks = retriever.search(rewritten.expanded_query, filters=sf, k_rrf=settings.rag_top_k * 3)
    ranked = reranker.rerank(rewritten.expanded_query, raw_chunks, top_k=settings.rag_top_k)

    assembler = ContextAssembler()
    assembled = assembler.assemble(ranked)

    system_prompt = _load_rag_prompt()
    user_message = (
        f"Fragmentos normativos de referencia:\n\n{assembled.context_text}"
        f"\n\n---\n\nConsulta: {req.query}"
    )

    anthropic = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    try:
        response = anthropic.messages.create(
            model=MODEL_OPUS,
            max_tokens=2048,
            temperature=0.1,  # type: ignore[arg-type]
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        answer_text = response.content[0].text  # type: ignore[union-attr]
    except Exception as exc:
        logger.error("rag_llm_error", error=str(exc))
        raise HTTPException(status_code=502, detail="LLM unavailable") from exc

    return AnswerResponse(
        answer=answer_text,
        citations=assembled.citation_mapping,
        query_rewritten=rewritten.expanded_query,
        model_used=MODEL_OPUS,
        prompt_version=_RAG_PROMPT_VERSION,
        verification_status="pending",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_filters(raw: dict[str, Any] | None) -> SearchFilters | None:
    if not raw:
        return None
    try:
        return SearchFilters(**raw)
    except Exception:
        return None
