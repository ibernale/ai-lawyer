"""Ops endpoints: agents, RAG status, memory, force-resync."""

from __future__ import annotations

import os
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_role
from lex_agents_api.settings import get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["ops"])

_admin_only = require_role("admin")


def _get_ssm() -> Any:
    try:
        from lex_agents_admin.state import get_system_state_manager
        return get_system_state_manager()
    except ImportError:
        return None


def _get_audit_mgr() -> Any:
    try:
        from lex_agents_audit.audit_trail import get_audit_trail_manager
        return get_audit_trail_manager()
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AgentStatus(BaseModel):
    name: str
    status: str  # active | killed | degraded
    current_prompt_version: str | None
    model: str
    kill_switch_engaged: bool
    invocations_last_24h: int
    avg_latency_ms_last_24h: float | None
    cost_usd_last_24h: float
    last_error: str | None


class CollectionInfo(BaseModel):
    name: str
    vectors_count: int
    payload_schema_keys: list[str]


class RagStatus(BaseModel):
    collections: list[CollectionInfo]
    total_vectors: int


class MemoryStatus(BaseModel):
    procedural_patterns_count: int
    semantic_files_count: int


class ProceduralPatternRow(BaseModel):
    filename: str
    content: str


class ForceResyncRequest(BaseModel):
    reason: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_NAMES = [
    "planner",
    "orchestrator",
    "coordinador",
    "judge",
    "specialist:banking",
    "specialist:securities",
]

_AGENT_MODELS: dict[str, str] = {
    "planner": "claude-sonnet-4-6",
    "orchestrator": "claude-sonnet-4-6",
    "coordinador": "claude-sonnet-4-6",
    "judge": "claude-sonnet-4-6",
    "specialist:banking": "claude-sonnet-4-6",
    "specialist:securities": "claude-sonnet-4-6",
}


def _prompt_versions_for(agent: str) -> list[str]:
    base = agent.split(":")[0]
    prompt_dir = os.path.join("docs", "prompts", base)
    try:
        return [f for f in os.listdir(prompt_dir) if f.endswith(".md")]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/agents", response_model=list[AgentStatus])
async def list_agents(
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> list[AgentStatus]:
    ssm = _get_ssm()
    result = []
    for name in _AGENT_NAMES:
        engaged = False
        if ssm:
            try:
                engaged = await ssm.is_killed(f"agent:{name}")
            except Exception:
                pass
        versions = _prompt_versions_for(name)
        current = versions[-1] if versions else None
        result.append(AgentStatus(
            name=name,
            status="killed" if engaged else "active",
            current_prompt_version=current,
            model=_AGENT_MODELS.get(name, "unknown"),
            kill_switch_engaged=engaged,
            invocations_last_24h=0,
            avg_latency_ms_last_24h=None,
            cost_usd_last_24h=0.0,
            last_error=None,
        ))
    return result


@router.get("/rag/status", response_model=RagStatus)
async def get_rag_status(
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> RagStatus:
    settings = get_settings()
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key.get_secret_value() or None)
        collections_resp = client.get_collections()
        infos: list[CollectionInfo] = []
        total = 0
        for col in collections_resp.collections:
            try:
                detail = client.get_collection(col.name)
                count = detail.indexed_vectors_count or 0
                schema_keys = list((detail.payload_schema or {}).keys())
            except Exception:
                count = 0
                schema_keys = []
            infos.append(CollectionInfo(name=col.name, vectors_count=count, payload_schema_keys=schema_keys))
            total += count
        return RagStatus(collections=infos, total_vectors=total)
    except Exception as exc:
        logger.warning("rag_status_unavailable", error=str(exc))
        return RagStatus(collections=[], total_vectors=0)


@router.get("/memory/status", response_model=MemoryStatus)
async def get_memory_status(
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> MemoryStatus:
    proc_count = 0
    sem_count = 0
    try:
        proc_count = len([f for f in os.listdir(os.path.join("docs", "memory", "procedural")) if f.endswith(".md")])
    except OSError:
        pass
    try:
        sem_count = len([f for f in os.listdir(os.path.join("docs", "memory", "semantic")) if f.endswith((".yml", ".yaml"))])
    except OSError:
        pass
    return MemoryStatus(procedural_patterns_count=proc_count, semantic_files_count=sem_count)


@router.get("/memory/procedural", response_model=list[ProceduralPatternRow])
async def list_procedural_patterns(
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> list[ProceduralPatternRow]:
    proc_dir = os.path.join("docs", "memory", "procedural")
    rows: list[ProceduralPatternRow] = []
    try:
        for fname in sorted(os.listdir(proc_dir)):
            if not fname.endswith(".md"):
                continue
            try:
                with open(os.path.join(proc_dir, fname)) as fh:
                    content = fh.read()
            except OSError:
                content = ""
            rows.append(ProceduralPatternRow(filename=fname, content=content))
    except OSError:
        pass
    return rows


@router.get("/memory/semantic/{filename}", response_model=dict[str, str])
async def get_semantic_file(
    filename: str,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> dict[str, str]:
    if ".." in filename or "/" in filename:
        raise HTTPException(400, "invalid filename")
    path = os.path.join("docs", "memory", "semantic", filename)
    try:
        with open(path) as fh:
            content = fh.read()
    except OSError as exc:
        raise HTTPException(404, "file not found") from exc
    return {"filename": filename, "content": content}


@router.put("/memory/procedural", status_code=204)
async def update_procedural_memory(
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> None:
    audit = _get_audit_mgr()
    if audit:
        await audit.log(
            "memory.procedural.edit", "memory",
            actor=user.username,
            actor_role=user.role,
            reason="manual edit via ops UI",
        )


@router.post("/sources/{name}/force-resync", status_code=204)
async def force_resync(
    name: str,
    body: ForceResyncRequest,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> None:
    if not body.reason.strip():
        raise HTTPException(422, "reason must not be empty")
    audit = _get_audit_mgr()
    if audit:
        await audit.log(
            "source.force_resync", "source",
            actor=user.username,
            actor_role=user.role,
            reason=body.reason,
            target_id=name,
        )
    logger.info("force_resync_requested", source=name, actor=user.username)
