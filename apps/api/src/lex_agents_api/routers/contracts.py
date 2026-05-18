"""Contract analysis endpoints — /api/v1/contracts."""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from lex_agents_agents.contracts.models import ContractAnalysis
from lex_agents_agents.contracts.orchestrator import ContractAnalysisRequest, ContractOrchestrator
from lex_agents_agents.contracts.store import ContractStore
from lex_agents_ingest.docling_extractor import DoclingExtractor
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])

# Supported MIME types for contract upload
_SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
# Max upload size for contracts: 20 MB
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class ContractAnalyzeResponse(BaseModel):
    contract_id: str
    trace_id: str
    status: str
    analysis: ContractAnalysis | None = None


# ---------------------------------------------------------------------------
# Dependency factories (lru_cache for process-lifetime singletons)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_contract_store(db_path: str) -> ContractStore:
    return ContractStore(db_path=db_path)


@lru_cache(maxsize=1)
def _get_orchestrator(anthropic_key: str) -> ContractOrchestrator:
    client = AnthropicClientWrapper(api_key=anthropic_key)
    return ContractOrchestrator(client)


@lru_cache(maxsize=1)
def _get_extractor() -> DoclingExtractor:
    return DoclingExtractor()


def get_contract_store(settings: Settings = Depends(get_settings)) -> ContractStore:
    return _get_contract_store(settings.consultation_db_path)


def get_contract_orchestrator(
    settings: Settings = Depends(get_settings),
) -> ContractOrchestrator:
    return _get_orchestrator(settings.anthropic_api_key.get_secret_value())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=ContractAnalyzeResponse)
async def analyze_contract(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_auth),
    orchestrator: ContractOrchestrator = Depends(get_contract_orchestrator),
    store: ContractStore = Depends(get_contract_store),
) -> ContractAnalyzeResponse:
    """Upload and analyze a contract document.

    Accepts PDF or DOCX. Returns the full ContractAnalysis synchronously.
    Typical latency: 15-45 seconds depending on contract length.
    """
    # Validate file type
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

    # Read and size-check the upload
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

    # Extract text
    extractor = _get_extractor()
    try:
        text, _page_count = extractor.extract(data, mime_type, filename)
    except Exception as exc:
        logger.exception("contract_extraction_failed", filename=filename, error=str(exc))
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

    contract_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    logger.info(
        "contract_analyze_start",
        contract_id=contract_id,
        trace_id=trace_id,
        filename=filename,
        text_chars=len(text),
        user=current_user.username,
        tenant_id=current_user.tenant_id,
    )

    # Run analysis synchronously (15-45 s; acceptable for interactive use)
    try:
        req = ContractAnalysisRequest(
            contract_id=contract_id,
            trace_id=trace_id,
            filename=filename,
            content=text,
        )
        analysis = await orchestrator.run(req)
    except Exception as exc:
        logger.exception(
            "contract_analysis_failed",
            contract_id=contract_id,
            trace_id=trace_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "ANALYSIS_FAILED",
                "message": "Contract analysis failed. Please retry.",
                "trace_id": trace_id,
            },
        ) from exc

    # Persist to store
    try:
        await store.save(analysis, tenant_id=current_user.tenant_id)
    except Exception:
        # Persistence failure should not fail the response — log and continue.
        logger.exception(
            "contract_persist_failed",
            contract_id=contract_id,
            trace_id=trace_id,
        )

    logger.info(
        "contract_analyze_complete",
        contract_id=contract_id,
        trace_id=trace_id,
        latency_ms=analysis.latency_ms,
        overall_rating=analysis.risk_assessment.overall_rating,
    )

    return ContractAnalyzeResponse(
        contract_id=contract_id,
        trace_id=trace_id,
        status="complete",
        analysis=analysis,
    )


@router.get("/{contract_id}", response_model=ContractAnalyzeResponse)
async def get_contract(
    contract_id: str,
    current_user: CurrentUser = Depends(require_auth),
    store: ContractStore = Depends(get_contract_store),
) -> ContractAnalyzeResponse:
    """Retrieve a previously analyzed contract by its ID."""
    analysis = await store.get(contract_id, tenant_id=current_user.tenant_id)
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONTRACT_NOT_FOUND", "message": f"Contract {contract_id!r} not found."},
        )
    return ContractAnalyzeResponse(
        contract_id=analysis.contract_id,
        trace_id=analysis.trace_id,
        status="complete",
        analysis=analysis,
    )


@router.get("", response_model=list[ContractAnalyzeResponse])
async def list_contracts(
    limit: int = 20,
    current_user: CurrentUser = Depends(require_auth),
    store: ContractStore = Depends(get_contract_store),
) -> list[Any]:
    """List the most recent analyzed contracts for the current tenant."""
    analyses = await store.list_recent(limit=limit, tenant_id=current_user.tenant_id)
    return [
        ContractAnalyzeResponse(
            contract_id=a.contract_id,
            trace_id=a.trace_id,
            status="complete",
            analysis=a,
        )
        for a in analyses
    ]
