"""Contract analysis endpoints — /api/v1/contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
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
    settings: Settings = Depends(get_settings),
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

    # Submit to admin review queue if risk is red or critical
    if analysis.risk_assessment.overall_rating in ("red", "critical"):
        await _maybe_queue_for_review(analysis, current_user.tenant_id, settings)

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


# ---------------------------------------------------------------------------
# Cross-contract comparison — Fase 13D
# ---------------------------------------------------------------------------


class ComparisonResult(BaseModel):
    contracts: list[ContractAnalyzeResponse]
    comparison: dict[str, Any]


@router.get("/compare", response_model=ComparisonResult)
async def compare_contracts(
    ids: list[str] = Query(..., description="2-5 contract IDs to compare"),
    current_user: CurrentUser = Depends(require_auth),
    store: ContractStore = Depends(get_contract_store),
) -> ComparisonResult:
    """Compare 2-5 previously analyzed contracts.

    Returns per-contract summaries plus a portfolio-level comparison:
    risk distribution, common compliance issues, obligation overlap,
    and a deterministic recommendation based on the risk mix.
    """
    if len(ids) < 2:
        raise HTTPException(status_code=422, detail={"code": "TOO_FEW_CONTRACTS", "message": "At least 2 contract IDs required."})
    if len(ids) > 5:
        raise HTTPException(status_code=422, detail={"code": "TOO_MANY_CONTRACTS", "message": "Maximum 5 contracts per comparison."})

    analyses: list[ContractAnalysis] = []
    for cid in ids:
        a = await store.get(cid, tenant_id=current_user.tenant_id)
        if a is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "CONTRACT_NOT_FOUND", "message": f"Contract {cid!r} not found."},
            )
        analyses.append(a)

    comparison = _build_comparison(analyses)

    return ComparisonResult(
        contracts=[
            ContractAnalyzeResponse(
                contract_id=a.contract_id,
                trace_id=a.trace_id,
                status="complete",
                analysis=a,
            )
            for a in analyses
        ],
        comparison=comparison,
    )


def _build_comparison(analyses: list[ContractAnalysis]) -> dict[str, Any]:
    # Risk distribution
    risk_dist: dict[str, int] = {"green": 0, "yellow": 0, "red": 0, "critical": 0}
    highest_risk_id = analyses[0].contract_id
    highest_risk_score = 0.0
    for a in analyses:
        risk_dist[a.risk_assessment.overall_rating] += 1
        if a.risk_assessment.overall_score > highest_risk_score:
            highest_risk_score = a.risk_assessment.overall_score
            highest_risk_id = a.contract_id

    # Common compliance issues
    from collections import defaultdict
    regulation_map: dict[str, list[str]] = defaultdict(list)
    for a in analyses:
        for cf in a.compliance_findings:
            if cf.status in ("non_compliant", "requires_review"):
                regulation_map[cf.regulation].append(a.contract_id)
    common_compliance = [
        {"regulation": reg, "affected_contracts": cids, "count": len(cids)}
        for reg, cids in regulation_map.items()
        if len(cids) > 1
    ]
    common_compliance.sort(key=lambda x: int(x["count"]), reverse=True)

    # Obligation overlap (obligations with ≥3 keyword matches across contracts)
    _sw = {"de", "del", "la", "el", "en", "a", "por", "con", "se", "su", "un", "una", "que", "y", "o", "no"}

    def _kw(text: str) -> frozenset[str]:
        return frozenset(w.strip(".,;:()[]") for w in text.lower().split() if w not in _sw and len(w) > 2)

    # Build obligation keyword sets per contract
    all_obl: list[tuple[str, str, frozenset[str]]] = []  # (contract_id, party, keywords)
    for a in analyses:
        for node in a.obligations.nodes:
            all_obl.append((a.contract_id, node.party, _kw(node.description)))

    # Find cross-contract obligation overlaps
    seen: set[tuple[str, ...]] = set()
    overlaps: list[dict[str, Any]] = []
    for i, (cid_i, party_i, kw_i) in enumerate(all_obl):
        for j, (cid_j, party_j, kw_j) in enumerate(all_obl):
            if j <= i or cid_i == cid_j:
                continue
            if len(kw_i & kw_j) >= 3:
                sorted_ids = tuple(sorted([cid_i, cid_j]))
                desc_key = " ".join(sorted(kw_i & kw_j)[:4])
                pair_key = (*sorted_ids, desc_key)
                if pair_key not in seen:
                    seen.add(pair_key)
                    overlaps.append({
                        "description": desc_key,
                        "parties": list({party_i, party_j}),
                        "contract_ids": list(sorted_ids),
                    })

    # Recommendation
    n_critical = risk_dist["critical"]
    n_red = risk_dist["red"]
    total = len(analyses)
    if n_critical > 0:
        recommendation = (
            f"Cartera de alto riesgo: {n_critical} de {total} contratos presentan riesgo crítico. "
            "Se recomienda revisión jurídica urgente antes de cualquier firma o ejecución."
        )
    elif n_red >= total // 2:
        recommendation = (
            f"{n_red} de {total} contratos presentan riesgo elevado. "
            "Priorizar la renegociación de las cláusulas críticas identificadas."
        )
    else:
        recommendation = (
            f"Cartera con perfil de riesgo moderado ({n_red} rojo, {risk_dist['yellow']} amarillo). "
            "Revisar los hallazgos de compliance compartidos entre contratos."
        )

    return {
        "risk_distribution": risk_dist,
        "common_compliance_issues": common_compliance[:10],
        "obligation_overlap": overlaps[:10],
        "highest_risk": highest_risk_id,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Audit queue helper — Fase 13D
# ---------------------------------------------------------------------------


async def _maybe_queue_for_review(
    analysis: ContractAnalysis,
    tenant_id: str,
    settings: Settings,
) -> None:
    """Silently add a high-risk contract analysis to the admin review queue."""
    try:
        from lex_agents_audit.audit_store import AuditSampleRecord, AuditStore

        audit_store = AuditStore(db_path=settings.consultation_db_path)
        record = AuditSampleRecord(
            trace_id=analysis.trace_id,
            query=f"[CONTRATO] {analysis.filename} — {analysis.metadata.document_type}",
            response_json=analysis.model_dump_json(),
            branch="analisis_contrato",
            depth=analysis.risk_assessment.overall_rating,
            sampled_at=datetime.now(UTC),
        )
        await audit_store.save(record)
        logger.info(
            "contract_queued_for_review",
            contract_id=analysis.contract_id,
            rating=analysis.risk_assessment.overall_rating,
        )
    except Exception:
        logger.warning(
            "contract_audit_queue_failed",
            contract_id=analysis.contract_id,
        )
