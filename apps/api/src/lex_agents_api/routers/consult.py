"""Consultation endpoints — /api/v1/consult."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

import anthropic as _anthropic
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from lex_agents_agents.orchestrator import (
    ConsultRequest,
    ConsultResponse,
    Orchestrator,
    OrchestratorDeps,
)
from lex_agents_agents.routing.unsupported_detector import detect_unsupported
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
from lex_agents_api.metrics import record_query, record_unsupported_query
from lex_agents_api.middleware import get_correlation_id
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/consult", tags=["consult"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


_VALID_JURISDICTIONS = {"ES", "EU", "UK", "BR", "MX", "US", "PL", "PT", "AR", "DE", "CH"}


class ConsultRequestBody(BaseModel):
    query: str = Field(min_length=10, max_length=4000)
    jurisdiction_hint: str | None = None
    jurisdictions: list[str] | None = None
    output_type: str | None = None  # dictamen|nota|memo_comite|analisis_riesgo|analisis_comparativo
    depth: Literal["shallow", "standard", "deep"] | None = None

    @field_validator("output_type")
    @classmethod
    def validate_output_type(cls, v: str | None) -> str | None:
        _VALID = {"dictamen", "nota", "memo_comite", "analisis_riesgo", "analisis_comparativo"}
        if v is not None and v not in _VALID:
            raise ValueError(f"output_type must be one of {_VALID}")
        return v

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        sanitized = _CONTROL_RE.sub("", v)
        if len(sanitized) < 10:
            raise ValueError("query too short after sanitization")
        return sanitized

    @field_validator("depth")
    @classmethod
    def validate_depth(
        cls, v: Literal["shallow", "standard", "deep"] | None
    ) -> Literal["shallow", "standard", "deep"] | None:
        if v is not None and v not in ("shallow", "standard", "deep"):
            raise ValueError("depth must be 'shallow', 'standard', or 'deep'")
        return v

    @field_validator("jurisdictions")
    @classmethod
    def validate_jurisdictions(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 5:
            raise ValueError("jurisdictions may contain at most 5 entries")
        unknown = [j for j in v if j.upper() not in _VALID_JURISDICTIONS]
        if unknown:
            raise ValueError(f"unknown jurisdiction codes: {unknown}")
        return [j.upper() for j in v]


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_embedder(model: str) -> BgeM3Embedder:
    return BgeM3Embedder(model=model)


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
    query_rewriter = LegalQueryRewriter(anthropic_client=_anthropic.Anthropic(api_key=anthropic_key))
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
    *,
    tenant_id: str = "default",
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
            depth_used=resp.depth_used,
            branch=resp.routing.get("branch") if resp.routing else None,
        )
        await store.save(record, tenant_id=tenant_id)
    except Exception:
        logger.exception("consultation_persist_failed", trace_id=trace_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ConsultResponse)
async def consult(
    body: ConsultRequestBody,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_auth),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    store: ConsultationStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> ConsultResponse:
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

    correlation_id = get_correlation_id()
    jurisdiction_hint = body.jurisdiction_hint
    if body.jurisdictions:
        jurisdiction_hint = ",".join(body.jurisdictions)
    req = ConsultRequest(
        query=body.query,
        jurisdiction_hint=jurisdiction_hint,
        output_type=body.output_type,
        depth=body.depth,
    )

    # Short-circuit for queries outside supported scope (no RAG/LLM needed)
    detection = detect_unsupported(body.query)
    if detection.detected:
        record_unsupported_query(detection.pattern or "unknown")
        degraded_trace = correlation_id or req.query[:8]
        degraded = ConsultResponse(
            trace_id=degraded_trace,
            answer=detection.degraded_response or "",
            citations=[],
            verification=None,
            query_rewritten=body.query,
            routing={"branch": "unsupported", "pattern": detection.pattern},
            metadata={},
            depth_used="none",
        )
        background_tasks.add_task(_persist, store, degraded_trace, body.query, degraded)
        return degraded

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
        depth_used=resp.depth_used,
        iterations=resp.iterations,
        planner_output=resp.planner_output,
        judge_verdict=resp.judge_verdict,
        cost_breakdown_by_agent=resp.cost_breakdown_by_agent,
        branch_answers=resp.branch_answers,
        comparative_output=resp.comparative_output,
    )

    record_query(
        depth=resp_with_cid.depth_used,
        branch=resp_with_cid.routing.get("branch", "unknown"),
        cost_usd=float(resp_with_cid.metadata.get("cost_estimate_usd") or 0.0),
    )
    background_tasks.add_task(_persist, store, resp_with_cid.trace_id, body.query, resp_with_cid, tenant_id=current_user.tenant_id)
    return resp_with_cid


@router.get("/{trace_id}", response_model=ConsultResponse)
async def get_consultation(
    trace_id: str,
    current_user: CurrentUser = Depends(require_auth),
    store: ConsultationStore = Depends(get_store),
) -> ConsultResponse:
    record = await store.get(trace_id, tenant_id=current_user.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Consultation {trace_id!r} not found")

    data: dict[str, Any] = json.loads(record.response_json)
    return ConsultResponse(**data)


@router.get("", response_model=list[dict[str, Any]])
async def list_consultations(
    limit: int = 20,
    offset: int = 0,
    q: str | None = None,
    depth: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    since: str | None = None,
    until: str | None = None,
    current_user: CurrentUser = Depends(require_auth),
    store: ConsultationStore = Depends(get_store),
) -> list[dict[str, Any]]:
    has_filters = any(p is not None for p in (q, depth, branch, status, since, until))
    if has_filters or offset:
        records = await store.search(
            q=q, depth=depth, branch=branch, status=status,
            since=since, until=until, limit=limit, offset=offset,
            tenant_id=current_user.tenant_id,
        )
    else:
        records = await store.list_recent(limit=limit, tenant_id=current_user.tenant_id)
    return [
        {
            "trace_id": r.trace_id,
            "created_at": r.created_at.isoformat(),
            "query": r.query[:80],
            "latency_ms": r.latency_ms,
            "verification_status": _extract_status(r.verification_json),
            "depth_used": r.depth_used,
            "branch": r.branch,
        }
        for r in records
    ]


def _extract_status(verification_json: str | None) -> str:
    if not verification_json:
        return "pending"
    try:
        data: dict[str, object] = json.loads(verification_json)
        return str(data.get("status", "unknown"))
    except Exception:
        return "unknown"
