"""Consultation endpoints — /api/v1/consult."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient

from lex_agents_agents.orchestrator import ConsultRequest, ConsultResponse, Orchestrator, OrchestratorDeps
from lex_agents_ingest.embedder import BgeM3Embedder
from lex_agents_rag.assembler import ContextAssembler
from lex_agents_rag.query_rewriter import LegalQueryRewriter
from lex_agents_rag.reranker import RerankerConfig, make_reranker
from lex_agents_rag.retriever import HybridRetriever
from lex_agents_shared.anthropic_client import AnthropicClientWrapper

from lex_agents_api.db import ConsultationRecord, ConsultationStore
from lex_agents_api.middleware import get_correlation_id
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/consult", tags=["consult"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ConsultRequestBody(BaseModel):
    query: str
    jurisdiction_hint: str | None = None
    output_type: str | None = None


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_embedder(model: str) -> BgeM3Embedder:
    return BgeM3Embedder(model_name=model)


@lru_cache(maxsize=1)
def _get_qdrant(url: str, api_key: str) -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key or None)


@lru_cache(maxsize=1)
def _get_store(db_path: str) -> ConsultationStore:
    return ConsultationStore(db_path=db_path)


@lru_cache(maxsize=1)
def _get_orchestrator(
    qdrant_url: str,
    qdrant_api_key: str,
    anthropic_key: str,
    embedder_model: str,
    reranker_model: str,
    reranker_enabled: bool,
    collection: str,
    rag_top_k: int,
) -> Orchestrator:
    embedder = _get_embedder(embedder_model)
    qdrant = _get_qdrant(qdrant_url, qdrant_api_key)
    retriever = HybridRetriever(
        qdrant_client=qdrant,
        embedder=embedder,
        collection=collection,
    )
    reranker = make_reranker(RerankerConfig(model=reranker_model, top_k=rag_top_k, enabled=reranker_enabled))
    query_rewriter = LegalQueryRewriter(anthropic_api_key=anthropic_key)
    assembler = ContextAssembler()
    client = AnthropicClientWrapper(api_key=anthropic_key)
    deps = OrchestratorDeps(
        retriever=retriever,
        reranker=reranker,
        query_rewriter=query_rewriter,
        assembler=assembler,
        client=client,
        verifier=None,  # wired in after verifier package is importable
        rag_top_k=rag_top_k,
    )
    return Orchestrator(deps)


def get_orchestrator(settings: Settings = Depends(get_settings)) -> Orchestrator:
    return _get_orchestrator(
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key.get_secret_value(),
        anthropic_key=settings.anthropic_api_key.get_secret_value(),
        embedder_model=settings.embedder_model,
        reranker_model=settings.reranker_model,
        reranker_enabled=settings.reranker_enabled,
        collection=settings.qdrant_collection,
        rag_top_k=settings.rag_top_k,
    )


def get_store(settings: Settings = Depends(get_settings)) -> ConsultationStore:
    return _get_store(settings.consultation_db_path)


# ---------------------------------------------------------------------------
# Background persistence helper
# ---------------------------------------------------------------------------

async def _persist(
    store: ConsultationStore,
    trace_id: str,
    query: str,
    resp: ConsultResponse,
) -> None:
    try:
        verification_json: str | None = None
        if resp.verification is not None:
            verification_json = resp.verification.model_dump_json()

        record = ConsultationRecord(
            trace_id=trace_id,
            created_at=datetime.now(timezone.utc),
            query=query,
            response_json=resp.model_dump_json(),
            verification_json=verification_json,
            prompt_versions={"specialist": resp.metadata.get("prompt_version")},  # type: ignore[arg-type]
            models=[resp.metadata.get("model", "")],  # type: ignore[list-item]
            latency_ms=resp.metadata.get("latency_ms"),  # type: ignore[arg-type]
            cost_estimate_usd=resp.metadata.get("cost_estimate_usd"),  # type: ignore[arg-type]
        )
        await store.save(record)
    except Exception:
        logger.exception("consultation_persist_failed", trace_id=trace_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ConsultResponse)
async def consult(
    body: ConsultRequestBody,
    background_tasks: BackgroundTasks,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    store: ConsultationStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> ConsultResponse:
    if not settings.agents_package_enabled:
        raise HTTPException(status_code=503, detail="Agents package disabled")

    correlation_id = get_correlation_id()
    req = ConsultRequest(
        query=body.query,
        jurisdiction_hint=body.jurisdiction_hint,
        output_type=body.output_type,
    )

    resp = await orchestrator.run(req)

    # Override trace_id with correlation_id for consistency
    resp_with_cid = ConsultResponse(
        trace_id=correlation_id or resp.trace_id,
        answer=resp.answer,
        citations=resp.citations,
        verification=resp.verification,
        query_rewritten=resp.query_rewritten,
        routing=resp.routing,
        metadata=resp.metadata,
    )

    background_tasks.add_task(_persist, store, resp_with_cid.trace_id, body.query, resp_with_cid)
    return resp_with_cid


@router.get("/{trace_id}", response_model=ConsultResponse)
async def get_consultation(
    trace_id: str,
    store: ConsultationStore = Depends(get_store),
) -> ConsultResponse:
    record = await store.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Consultation {trace_id!r} not found")

    data: dict[str, Any] = json.loads(record.response_json)
    return ConsultResponse(**data)


@router.get("", response_model=list[dict[str, Any]])
async def list_consultations(
    limit: int = 20,
    store: ConsultationStore = Depends(get_store),
) -> list[dict[str, Any]]:
    records = await store.list_recent(limit=limit)
    return [
        {
            "trace_id": r.trace_id,
            "created_at": r.created_at.isoformat(),
            "query": r.query[:80],
            "latency_ms": r.latency_ms,
            "verification_status": _extract_status(r.verification_json),
        }
        for r in records
    ]


def _extract_status(verification_json: str | None) -> str:
    if not verification_json:
        return "pending"
    try:
        data = json.loads(verification_json)
        return data.get("status", "unknown")
    except Exception:
        return "unknown"
