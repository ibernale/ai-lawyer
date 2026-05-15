"""Ops endpoints: agents, RAG status, memory, force-resync."""

from __future__ import annotations

import os
from typing import Annotated, Any

import bcrypt as _bcrypt
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


# ---------------------------------------------------------------------------
# Users (read-only list — passwords never exposed)
# ---------------------------------------------------------------------------

class UserRow(BaseModel):
    username: str
    role: str


@router.get("/users", response_model=list[UserRow])
async def list_users(
    user: Annotated[CurrentUser, Depends(_admin_only)],
    settings: Annotated[Any, Depends(get_settings)],
) -> list[UserRow]:
    """Return all configured users (without password hashes)."""
    from lex_agents_api.auth import _load_users

    return [
        UserRow(username=u.username, role=u.role)
        for u in _load_users(settings)
    ]


# ---------------------------------------------------------------------------
# User CRUD endpoints
# ---------------------------------------------------------------------------

_VALID_ROLES = frozenset({"admin", "operator", "auditor", "analyst"})


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "analyst"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    password: str | None = None
    disabled: bool | None = None


@router.post("/users", response_model=UserRow, status_code=201)
async def create_user(
    body: CreateUserRequest,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> UserRow:
    """Create a new platform user."""
    if body.role not in _VALID_ROLES:
        raise HTTPException(422, f"Invalid role: {body.role}")
    if len(body.username) < 2 or len(body.username) > 64:
        raise HTTPException(422, "Username must be 2-64 characters")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")

    try:
        from lex_agents_admin.user_store import get_user_store
        store = get_user_store()
    except ImportError:
        store = None

    if store is None:
        raise HTTPException(503, "User store not available")

    password_hash = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt(rounds=12)).decode()
    ok = await store.create(body.username, password_hash, body.role)
    if not ok:
        raise HTTPException(409, f"User '{body.username}' already exists")

    audit = _get_audit_mgr()
    if audit:
        try:
            await audit.log("user.invite.send", "user", user.username, user.role,
                            reason="Admin created user", target_id=body.username,
                            after={"role": body.role})
        except Exception as _e:
            logger.warning("audit_write_failed", error=str(_e))

    return UserRow(username=body.username, role=body.role)


@router.patch("/users/{username}", response_model=UserRow)
async def update_user(
    username: str,
    body: UpdateUserRequest,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> UserRow:
    """Update a user's role, password, or disabled state."""
    if body.role is not None and body.role not in _VALID_ROLES:
        raise HTTPException(422, f"Invalid role: {body.role}")
    if body.password is not None and len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")

    try:
        from lex_agents_admin.user_store import get_user_store
        store = get_user_store()
    except ImportError:
        store = None

    if store is None:
        raise HTTPException(503, "User store not available")

    password_hash = None
    if body.password:
        password_hash = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt(rounds=12)).decode()

    ok = await store.update(username, role=body.role, password_hash=password_hash, disabled=body.disabled)
    if not ok:
        raise HTTPException(404, f"User '{username}' not found")

    record = await store.get_by_username(username)

    audit = _get_audit_mgr()
    if audit:
        try:
            if body.disabled is True:
                action = "user.disable"
            elif body.disabled is False:
                action = "user.enable"
            else:
                action = "user.role.change"
            await audit.log(action, "user", user.username, user.role,
                            reason="Admin updated user", target_id=username,
                            after={"role": body.role, "disabled": body.disabled})
        except Exception as _e:
            logger.warning("audit_write_failed", error=str(_e))

    return UserRow(username=username, role=record.role if record else (body.role or "analyst"))


@router.delete("/users/{username}", status_code=204)
async def delete_user(
    username: str,
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> None:
    """Delete a user permanently."""
    if username == user.username:
        raise HTTPException(409, "Cannot delete your own account")

    try:
        from lex_agents_admin.user_store import get_user_store
        store = get_user_store()
    except ImportError:
        store = None

    if store is None:
        raise HTTPException(503, "User store not available")

    ok = await store.delete(username)
    if not ok:
        raise HTTPException(404, f"User '{username}' not found")

    audit = _get_audit_mgr()
    if audit:
        try:
            await audit.log("user.delete", "user", user.username, user.role,
                            reason="Admin deleted user", target_id=username)
        except Exception as _e:
            logger.warning("audit_write_failed", error=str(_e))


# ---------------------------------------------------------------------------
# Pipelines endpoint
# ---------------------------------------------------------------------------

class PipelineExecution(BaseModel):
    name: str
    execution_arn: str
    status: str  # RUNNING | SUCCEEDED | FAILED | TIMED_OUT | ABORTED
    start_date: str | None
    stop_date: str | None


class PipelinesResponse(BaseModel):
    executions: list[PipelineExecution]
    status: str  # ok | unavailable | not_configured
    message: str | None = None


@router.get("/pipelines", response_model=PipelinesResponse)
async def list_pipelines(
    user: Annotated[CurrentUser, Depends(_admin_only)],
) -> PipelinesResponse:
    """List recent Step Functions pipeline executions."""
    try:
        import boto3
        sfn = boto3.client("stepfunctions")
        machines = sfn.list_state_machines(maxResults=20)
        executions: list[PipelineExecution] = []
        for sm in machines.get("stateMachines", []):
            arn = sm["stateMachineArn"]
            try:
                execs = sfn.list_executions(stateMachineArn=arn, maxResults=5)
                for ex in execs.get("executions", []):
                    executions.append(PipelineExecution(
                        name=ex.get("name", ""),
                        execution_arn=ex.get("executionArn", ""),
                        status=ex.get("status", ""),
                        start_date=ex["startDate"].isoformat() if ex.get("startDate") else None,
                        stop_date=ex["stopDate"].isoformat() if ex.get("stopDate") else None,
                    ))
            except Exception:
                pass
        return PipelinesResponse(executions=executions, status="ok")
    except ImportError:
        return PipelinesResponse(executions=[], status="not_configured", message="boto3 not installed")
    except Exception as exc:
        logger.warning("pipelines_unavailable", error=str(exc))
        return PipelinesResponse(executions=[], status="unavailable", message=str(exc))


# ---------------------------------------------------------------------------
# Platform config endpoint
# ---------------------------------------------------------------------------

class ServiceConfig(BaseModel):
    name: str
    configured: bool
    value_hint: str | None = None  # masked/partial value


class PlatformConfig(BaseModel):
    env: str
    db_mode: str
    auth_enabled: bool
    log_level: str
    services: list[ServiceConfig]
    jwt_algorithm: str
    otel_service_name: str


@router.get("/platform-config", response_model=PlatformConfig)
async def get_platform_config(
    user: Annotated[CurrentUser, Depends(_admin_only)],
    settings: Annotated[Any, Depends(get_settings)],
) -> PlatformConfig:
    """Return masked platform configuration for the settings page."""
    from lex_agents_shared.db import is_postgres

    def _masked(val: str, show: int = 4) -> str | None:
        if not val:
            return None
        return val[:show] + "****" if len(val) > show else "****"

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    qdrant_key_raw = ""
    try:
        qdrant_key_raw = settings.qdrant_api_key.get_secret_value()
    except Exception:
        pass

    services = [
        ServiceConfig(name="Anthropic API", configured=bool(anthropic_key), value_hint=_masked(anthropic_key)),
        ServiceConfig(name="Qdrant", configured=bool(settings.qdrant_url), value_hint=settings.qdrant_url or None),
        ServiceConfig(name="Qdrant API Key", configured=bool(qdrant_key_raw), value_hint=_masked(qdrant_key_raw) if qdrant_key_raw else None),
        ServiceConfig(name="OTEL Exporter", configured=bool(settings.otel_exporter_otlp_endpoint), value_hint=settings.otel_exporter_otlp_endpoint or None),
    ]

    return PlatformConfig(
        env=settings.env,
        db_mode="aurora" if is_postgres() else "sqlite",
        auth_enabled=settings.auth_enabled,
        log_level=settings.log_level,
        services=services,
        jwt_algorithm=settings.jwt_algorithm,
        otel_service_name=settings.otel_service_name,
    )
