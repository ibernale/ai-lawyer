"""SSE streaming endpoint — POST /api/v1/consult/stream."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, AsyncGenerator

import anthropic as _anthropic
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from lex_agents_agents.core.orchestrator_v2 import (
    ConsultRequest,
    ConsultResponse,
    OrchestratorDeps,
    OrchestratorV2,
    SseEvent,
)
from lex_agents_ingest.embedder import BgeM3Embedder
from lex_agents_rag.assembler import ContextAssembler
from lex_agents_rag.query_rewriter import LegalQueryRewriter
from lex_agents_rag.reranker import RerankerConfig, make_reranker
from lex_agents_rag.retriever import HybridRetriever
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from lex_agents_verifier.pipeline import VerifierPipeline
from pydantic import BaseModel, Field, field_validator
from qdrant_client import QdrantClient

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.db import ConsultationRecord, ConsultationStore
from lex_agents_api.middleware import get_correlation_id
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/consult", tags=["consult-stream"])

# ---------------------------------------------------------------------------
# Dependency factories (separate cache from consult.py to allow independent
# lifecycle; both share the same Settings singleton)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_embedder_v2(model: str) -> BgeM3Embedder:
    return BgeM3Embedder(model=model)


@lru_cache(maxsize=1)
def _get_qdrant_v2(url: str, api_key: str) -> QdrantClient:
    return QdrantClient(url=url, api_key=api_key or None)


@lru_cache(maxsize=1)
def _get_store_v2(db_path: str) -> ConsultationStore:
    return ConsultationStore(db_path=db_path)


@lru_cache(maxsize=1)
def _get_orchestrator_v2(
    qdrant_url: str,
    qdrant_api_key: str,
    anthropic_key: str,
    embedder_model: str,
    reranker_model: str,
    reranker_enabled: bool,
    collection: str,
    rag_top_k: int,
) -> OrchestratorV2:
    embedder = _get_embedder_v2(embedder_model)
    qdrant = _get_qdrant_v2(qdrant_url, qdrant_api_key)
    retriever = HybridRetriever(
        qdrant_client=qdrant,
        embedder=embedder,
        collection=collection,
    )
    reranker = make_reranker(
        RerankerConfig(model=reranker_model, top_k=rag_top_k, enabled=reranker_enabled)
    )
    query_rewriter = LegalQueryRewriter(
        anthropic_client=_anthropic.Anthropic(api_key=anthropic_key)
    )
    assembler = ContextAssembler()
    client = AnthropicClientWrapper(api_key=anthropic_key)
    verifier = VerifierPipeline(anthropic_client=client)
    deps = OrchestratorDeps(
        retriever=retriever,
        reranker=reranker,
        query_rewriter=query_rewriter,
        assembler=assembler,
        client=client,
        verifier=verifier,
        rag_top_k=rag_top_k,
    )
    return OrchestratorV2(deps)


def _get_orch_v2(settings: Settings = Depends(get_settings)) -> OrchestratorV2:
    return _get_orchestrator_v2(
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key.get_secret_value(),
        anthropic_key=settings.anthropic_api_key.get_secret_value(),
        embedder_model=settings.embedder_model,
        reranker_model=settings.reranker_model,
        reranker_enabled=settings.reranker_enabled,
        collection=settings.qdrant_collection,
        rag_top_k=settings.rag_top_k,
    )


def _get_store_dep(settings: Settings = Depends(get_settings)) -> ConsultationStore:
    return _get_store_v2(settings.consultation_db_path)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_encode(event: SseEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, default=str)}\n\n"


async def _event_generator(
    orchestrator: OrchestratorV2,
    req: ConsultRequest,
) -> AsyncGenerator[str, None]:
    async for event in orchestrator.run_streaming(req):
        yield _sse_encode(event)


# ---------------------------------------------------------------------------
# Background persistence (mirrors consult.py)
# ---------------------------------------------------------------------------


async def _persist_stream(
    store: ConsultationStore,
    trace_id: str,
    query: str,
    resp: ConsultResponse,
) -> None:
    try:
        verification_json: str | None = None
        if resp.verification is not None:
            verification_json = resp.verification.model_dump_json()
        pv = resp.metadata.get("prompt_version")
        prompt_versions: dict[str, int] | None = (
            {"specialist": int(pv)} if pv is not None else None
        )
        model_val = resp.metadata.get("model")
        models: list[str] | None = [str(model_val)] if model_val is not None else None
        lat = resp.metadata.get("latency_ms")
        cost = resp.metadata.get("cost_estimate_usd")
        from datetime import UTC, datetime
        from lex_agents_api.db import ConsultationRecord
        record = ConsultationRecord(
            trace_id=trace_id,
            created_at=datetime.now(UTC),
            query=query,
            response_json=resp.model_dump_json(),
            verification_json=verification_json,
            prompt_versions=prompt_versions,
            models=models,
            latency_ms=int(lat) if lat is not None else None,
            cost_estimate_usd=float(cost) if cost is not None else None,
        )
        await store.save(record)
    except Exception:
        logger.exception("stream_consultation_persist_failed", trace_id=trace_id)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/stream")
async def consult_stream(
    body: dict[str, Any],
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_auth),
    orchestrator: OrchestratorV2 = Depends(_get_orch_v2),
    store: ConsultationStore = Depends(_get_store_dep),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    if not settings.agents_package_enabled:
        raise HTTPException(status_code=503, detail="Agents package disabled")

    try:
        from lex_agents_admin.state import get_system_state_manager
        ssm = get_system_state_manager()
        if ssm and await ssm.is_killed("global"):
            reason = await ssm.get_kill_reason("global") or "Sistema pausado por administración"
            raise HTTPException(503, detail={"code": "SYSTEM_KILLED", "reason": reason})
    except HTTPException:
        raise
    except Exception:
        pass

    query: str = body.get("query", "")
    if not isinstance(query, str) or len(query.strip()) < 10:
        raise HTTPException(status_code=422, detail="query must be at least 10 characters")

    jurisdiction_hint: str | None = body.get("jurisdiction_hint")
    jurisdictions: list[str] | None = body.get("jurisdictions")
    if jurisdictions:
        jurisdiction_hint = ",".join(jurisdictions)

    req = ConsultRequest(
        query=query,
        jurisdiction_hint=jurisdiction_hint,
        output_type=body.get("output_type"),
        depth=body.get("depth"),
    )

    correlation_id = get_correlation_id()

    async def _generate() -> AsyncGenerator[str, None]:
        final_resp: ConsultResponse | None = None
        try:
            async for event in orchestrator.run_streaming(req):
                yield _sse_encode(event)
                if event.event == "result":
                    try:
                        final_resp = ConsultResponse.model_validate(event.data)
                    except Exception:
                        pass
        except Exception as exc:
            logger.exception("stream_pipeline_error")
            yield _sse_encode(SseEvent("error", {"message": str(exc)}))
            yield _sse_encode(SseEvent("done", {}))
            return
        if final_resp is not None:
            trace_id = correlation_id or final_resp.trace_id
            background_tasks.add_task(_persist_stream, store, trace_id, query, final_resp)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
