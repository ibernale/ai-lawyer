"""Document upload, analysis, and comparison endpoints — /api/v1/documents."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import anthropic as _anthropic
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.middleware import get_correlation_id
from lex_agents_api.settings import Settings, get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# In-memory document store (TTL 30 min, never persisted to disk — ADR 0026)
# ---------------------------------------------------------------------------

_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
_DOCUMENT_TTL = timedelta(minutes=30)

_store: dict[str, dict[str, Any]] = {}  # doc_id -> {parsed_doc, expires_at}


def _put_document(doc_id: str, parsed_doc: Any) -> None:
    _store[doc_id] = {
        "parsed_doc": parsed_doc,
        "expires_at": datetime.now(UTC) + _DOCUMENT_TTL,
    }


def _get_document(doc_id: str) -> Any:
    entry = _store.get(doc_id)
    if entry is None:
        return None
    if datetime.now(UTC) > entry["expires_at"]:
        del _store[doc_id]
        return None
    return entry["parsed_doc"]


def _delete_document(doc_id: str) -> bool:
    return _store.pop(doc_id, None) is not None


def _purge_expired() -> None:
    now = datetime.now(UTC)
    expired = [k for k, v in _store.items() if now > v["expires_at"]]
    for k in expired:
        del _store[k]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    sha256: str
    mime_type: str
    segment_count: int
    page_count: int | None = None
    expires_at: datetime


class AnalysisResponse(BaseModel):
    doc_id: str
    trace_id: str
    filename: str
    mode: str
    analysis_text: str
    segment_count: int
    verification_status: str = "amber"
    analysed_at: datetime


class CompareResponse(BaseModel):
    doc_ids: list[str]
    trace_id: str
    diff_text: str
    verification_status: str = "amber"
    analysed_at: datetime


# ---------------------------------------------------------------------------
# Dependency: lazy import documents package (optional dep)
# ---------------------------------------------------------------------------


def _get_documents_pipeline():  # type: ignore[return]
    try:
        from lex_agents_documents.parsers.dispatcher import detect_and_parse
        from lex_agents_documents.entities import EntityExtractor
        return detect_and_parse, EntityExtractor()
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "DOCUMENTS_NOT_AVAILABLE", "message": str(exc)}},
        ) from exc


def _get_analyst():  # type: ignore[return]
    try:
        from lex_agents_agents.specialists.document_analyst import DocumentAnalystSpecialist
        client = _anthropic.Anthropic()
        return DocumentAnalystSpecialist(client)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "ANALYST_NOT_AVAILABLE", "message": str(exc)}},
        ) from exc


# ---------------------------------------------------------------------------
# POST /api/v1/documents/upload
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    _user: CurrentUser = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    _purge_expired()

    raw_bytes = await file.read()

    if len(raw_bytes) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error": {"code": "FILE_TOO_LARGE", "message": "File exceeds 50 MB"}},
        )

    detect_and_parse, _ = _get_documents_pipeline()

    doc_id = str(uuid.uuid4())
    correlation_id = get_correlation_id()

    try:
        parsed_doc = detect_and_parse(raw_bytes, file.filename or "upload", doc_id)
    except Exception as exc:
        error_name = type(exc).__name__
        logger.warning(
            "document.upload.parse_error",
            doc_id=doc_id,
            error=error_name,
            correlation_id=correlation_id,
        )
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": error_name.upper(), "message": str(exc)}},
        ) from exc

    _put_document(doc_id, parsed_doc)

    expires_at = datetime.now(UTC) + _DOCUMENT_TTL

    logger.info(
        "document.uploaded",
        doc_id=doc_id,
        filename=parsed_doc.filename,
        mime_type=parsed_doc.mime_type,
        segment_count=len(parsed_doc.segments),
        correlation_id=correlation_id,
    )

    return UploadResponse(
        doc_id=doc_id,
        filename=parsed_doc.filename,
        sha256=parsed_doc.sha256,
        mime_type=parsed_doc.mime_type,
        segment_count=len(parsed_doc.segments),
        page_count=parsed_doc.page_count,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/documents/{doc_id}/analyze
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    query: str = Field(default="Analiza este documento.", min_length=5, max_length=2000)
    mode: str = Field(
        default="riesgos",
        description="resumen_ejecutivo | analisis_clausulas | riesgos | comparativa",
    )


@router.post("/{doc_id}/analyze", response_model=AnalysisResponse)
async def analyze_document(
    doc_id: str,
    body: AnalyzeRequest,
    _user: CurrentUser = Depends(require_auth),
) -> AnalysisResponse:
    parsed_doc = _get_document(doc_id)
    if parsed_doc is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "DOCUMENT_NOT_FOUND", "message": f"Document {doc_id} not found or expired"}},
        )

    valid_modes = {"resumen_ejecutivo", "analisis_clausulas", "riesgos", "comparativa"}
    if body.mode not in valid_modes:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_MODE", "message": f"mode must be one of {valid_modes}"}},
        )

    analyst = _get_analyst()
    trace_id = str(uuid.uuid4())
    correlation_id = get_correlation_id()

    # Build [DOC:s] annotated context
    doc_lines: list[str] = [f"DOCUMENTO: {parsed_doc.filename}", "---"]
    for seg in parsed_doc.segments:
        doc_lines.append(f"[DOC:{seg.index}] {seg.heading or seg.segment_type.upper()}")
        doc_lines.append(seg.text)
        doc_lines.append("")
    doc_context = "\n".join(doc_lines)

    logger.info(
        "document.analyse.start",
        doc_id=doc_id,
        trace_id=trace_id,
        mode=body.mode,
        segment_count=len(parsed_doc.segments),
        correlation_id=correlation_id,
    )

    try:
        analysis_text = await analyst.analyse(
            doc_context=doc_context,
            query=body.query,
            rag_chunks=[],
            mode=body.mode,  # type: ignore[arg-type]
        )
    except Exception as exc:
        logger.error(
            "document.analyse.error",
            doc_id=doc_id,
            trace_id=trace_id,
            error=str(exc),
            correlation_id=correlation_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "ANALYSIS_FAILED", "message": "Analysis failed"}},
        ) from exc

    logger.info(
        "document.analyse.done",
        doc_id=doc_id,
        trace_id=trace_id,
        response_length=len(analysis_text),
        correlation_id=correlation_id,
    )

    return AnalysisResponse(
        doc_id=doc_id,
        trace_id=trace_id,
        filename=parsed_doc.filename,
        mode=body.mode,
        analysis_text=analysis_text,
        segment_count=len(parsed_doc.segments),
        verification_status="amber",
        analysed_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/documents/compare
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=2, max_length=2)
    query: str = Field(default="Compara estos dos documentos.", min_length=5, max_length=2000)


@router.post("/compare", response_model=CompareResponse)
async def compare_documents(
    body: CompareRequest,
    _user: CurrentUser = Depends(require_auth),
) -> CompareResponse:
    docs = []
    for doc_id in body.doc_ids:
        parsed_doc = _get_document(doc_id)
        if parsed_doc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "DOCUMENT_NOT_FOUND", "message": f"Document {doc_id} not found or expired"}},
            )
        docs.append(parsed_doc)

    analyst = _get_analyst()
    trace_id = str(uuid.uuid4())
    correlation_id = get_correlation_id()

    # Build combined context with both documents
    combined_lines: list[str] = []
    for i, doc in enumerate(docs, start=1):
        combined_lines.append(f"DOCUMENTO {i}: {doc.filename}")
        combined_lines.append("---")
        for seg in doc.segments:
            combined_lines.append(f"[DOC:{seg.index}] {seg.heading or seg.segment_type.upper()}")
            combined_lines.append(seg.text)
            combined_lines.append("")
        combined_lines.append("")

    doc_context = "\n".join(combined_lines)

    try:
        diff_text = await analyst.analyse(
            doc_context=doc_context,
            query=body.query,
            rag_chunks=[],
            mode="comparativa",
        )
    except Exception as exc:
        logger.error(
            "document.compare.error",
            trace_id=trace_id,
            error=str(exc),
            correlation_id=correlation_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "COMPARISON_FAILED", "message": "Comparison failed"}},
        ) from exc

    return CompareResponse(
        doc_ids=body.doc_ids,
        trace_id=trace_id,
        diff_text=diff_text,
        verification_status="amber",
        analysed_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/documents/{doc_id}
# ---------------------------------------------------------------------------


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    _user: CurrentUser = Depends(require_auth),
) -> None:
    deleted = _delete_document(doc_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "DOCUMENT_NOT_FOUND", "message": f"Document {doc_id} not found or already deleted"}},
        )
    logger.info("document.deleted", doc_id=doc_id)
