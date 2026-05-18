"""Risk matrix endpoints — /api/v1/consult/{trace_id}/risk-matrix."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from lex_agents_agents.risk_matrix import RiskMatrixGenerator
from lex_agents_agents.risk_matrix_xlsx import build_risk_matrix_xlsx
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.db import ConsultationStore
from lex_agents_api.settings import get_settings

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/consult", tags=["risk-matrix"])

# ---------------------------------------------------------------------------
# Response model (JSON summary, not the full XLSX)
# ---------------------------------------------------------------------------


class RiskMatrixSummary(BaseModel):
    trace_id: str
    query: str
    n_items: int
    n_alto: int
    n_medio: int
    n_bajo: int
    generated_at: str


# ---------------------------------------------------------------------------
# Endpoint: POST /api/v1/consult/{trace_id}/risk-matrix/xlsx
# ---------------------------------------------------------------------------


@router.post(
    "/{trace_id}/risk-matrix/xlsx",
    summary="Generate and download a risk matrix as XLSX",
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            },
            "description": "XLSX workbook with colour-coded risk matrix",
        },
        404: {"description": "Consultation not found"},
    },
)
async def generate_risk_matrix_xlsx(
    trace_id: str,
    current_user: CurrentUser = Depends(require_auth),
) -> Response:
    """Generate a risk matrix XLSX for a completed consultation.

    Reads the stored consultation from DB, calls Claude to extract
    structured risk items, and returns a two-sheet XLSX workbook.
    """
    settings = get_settings()
    store = ConsultationStore(settings.consultation_db_path)
    await store.init()

    record = await store.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Consultation {trace_id!r} not found")

    # Reconstruct a minimal ConsultResponse from the stored record
    from lex_agents_agents.orchestrator import ConsultResponse

    try:
        consult_response = ConsultResponse.model_validate_json(record.response_json)
    except Exception as exc:
        logger.error("risk_matrix_response_parse_error", trace_id=trace_id, error=str(exc))
        raise HTTPException(status_code=422, detail="Could not parse stored consultation") from exc

    settings = get_settings()
    client = AnthropicClientWrapper(api_key=settings.anthropic_api_key.get_secret_value())
    gen = RiskMatrixGenerator(client)

    try:
        matrix = gen.generate(consult_response, query=record.query)
    except Exception as exc:
        logger.error("risk_matrix_generation_error", trace_id=trace_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Risk matrix generation failed") from exc

    try:
        xlsx_bytes = build_risk_matrix_xlsx(matrix)
    except Exception as exc:
        logger.error("risk_matrix_xlsx_build_error", trace_id=trace_id, error=str(exc))
        raise HTTPException(status_code=500, detail="XLSX build failed") from exc

    filename = f"matriz_riesgos_{trace_id[:8]}.xlsx"
    logger.info(
        "risk_matrix_xlsx_generated",
        trace_id=trace_id,
        n_items=len(matrix.items),
        size_bytes=len(xlsx_bytes),
    )

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
