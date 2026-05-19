"""Contract analysis SSE streaming endpoint — POST /api/v1/contracts/analyze/stream."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from lex_agents_agents.contracts.models import ContractAnalysis
from lex_agents_agents.contracts.orchestrator import ContractAnalysisRequest, ContractOrchestrator
from lex_agents_agents.contracts.store import ContractStore
from lex_agents_ingest.docling_extractor import DoclingExtractor
from lex_agents_shared.anthropic_client import AnthropicClientWrapper

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/contracts", tags=["contracts-stream"])

_SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_contract_store_stream(db_path: str) -> ContractStore:
    return ContractStore(db_path=db_path)


@lru_cache(maxsize=1)
def _get_orchestrator_stream(anthropic_key: str) -> ContractOrchestrator:
    client = AnthropicClientWrapper(api_key=anthropic_key)
    return ContractOrchestrator(client)


@lru_cache(maxsize=1)
def _get_extractor_stream() -> DoclingExtractor:
    return DoclingExtractor()


def get_contract_store_stream(settings: Settings = Depends(get_settings)) -> ContractStore:
    return _get_contract_store_stream(settings.consultation_db_path)


def get_contract_orchestrator_stream(
    settings: Settings = Depends(get_settings),
) -> ContractOrchestrator:
    return _get_orchestrator_stream(settings.anthropic_api_key.get_secret_value())


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def _fmt_sse(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE message."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _validate_and_extract(
    file: UploadFile, trace_id: str
) -> tuple[str, str, bytes]:
    """Validate upload and extract text. Raises HTTPException on failure.

    Returns (filename, text, raw_bytes).
    """
    filename = file.filename or "unknown"
    mime_type = file.content_type or ""

    is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")
    is_docx = mime_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ) or filename.lower().endswith((".docx", ".doc"))

    if not is_pdf and not is_docx:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_FILE_TYPE",
                "message": (
                    f"File type not supported: {mime_type!r}. "
                    "Only PDF and DOCX files are accepted."
                ),
            },
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"File exceeds maximum size of {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            },
        )
    if not data:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_FILE", "message": "Uploaded file is empty."},
        )

    extractor = _get_extractor_stream()
    try:
        text, _page_count = extractor.extract(data, mime_type, filename)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EXTRACTION_FAILED",
                "message": f"Could not extract text from document: {exc}",
            },
        ) from exc

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_DOCUMENT", "message": "No text could be extracted from the document."},
        )

    return filename, text, data


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/analyze/stream")
async def analyze_contract_stream(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_auth),
    orchestrator: ContractOrchestrator = Depends(get_contract_orchestrator_stream),
    store: ContractStore = Depends(get_contract_store_stream),
) -> StreamingResponse:
    """Upload a contract and stream analysis progress via SSE.

    Returns a text/event-stream with the following event types:
    - progress: {"step": str, "message": str, "pct": int}
    - result:   {"analysis": ContractAnalysis JSON}
    - done:     {}
    - error:    {"message": str, "trace_id": str}

    The final `result` event contains the full ContractAnalysis. The client
    should switch from the progress view to the analysis view on this event.
    """
    contract_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    try:
        filename, text, _raw = await _validate_and_extract(file, trace_id)
    except HTTPException:
        raise

    logger.info(
        "contract_stream_start",
        contract_id=contract_id,
        trace_id=trace_id,
        filename=filename,
        text_chars=len(text),
        user=current_user.username,
        tenant_id=current_user.tenant_id,
    )

    req = ContractAnalysisRequest(
        contract_id=contract_id,
        trace_id=trace_id,
        filename=filename,
        content=text,
    )

    async def _event_generator() -> AsyncGenerator[str, None]:
        analysis_result: ContractAnalysis | None = None

        async for sse_event in orchestrator.run_streaming(req):
            yield _fmt_sse(sse_event.event, sse_event.data)

            if sse_event.event == "result":
                # Capture the analysis for background persistence
                try:
                    analysis_result = ContractAnalysis.model_validate(sse_event.data)
                except Exception:
                    logger.exception(
                        "contract_stream_result_parse_error",
                        contract_id=contract_id,
                    )

        if analysis_result is not None:
            background_tasks.add_task(
                _persist_analysis, store, analysis_result, current_user.tenant_id
            )

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-Contract-Id": contract_id,
            "X-Trace-Id": trace_id,
        },
    )


async def _persist_analysis(
    store: ContractStore, analysis: ContractAnalysis, tenant_id: str
) -> None:
    """Background task: persist analysis to store after streaming completes."""
    try:
        await store.save(analysis, tenant_id=tenant_id)
        logger.info("contract_stream_persisted", contract_id=analysis.contract_id)
    except Exception:
        logger.exception(
            "contract_stream_persist_failed",
            contract_id=analysis.contract_id,
        )
