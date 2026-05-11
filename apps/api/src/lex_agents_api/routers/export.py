"""Export and feedback endpoints for consultations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import structlog
from docx import Document
from docx.shared import Pt, RGBColor
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lex_agents_api.auth import CurrentUser, require_auth
from lex_agents_api.db import ConsultationStore
from lex_agents_api.routers.consult import get_store

logger: structlog.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/consult", tags=["export"])

_DISCLAIMER = (
    "AVISO LEGAL: Este documento es un borrador generado asistidamente por IA "
    "(lex-agents v0.1.0). Requiere validación por un jurista cualificado antes de "
    "cualquier uso externo. No constituye asesoramiento jurídico profesional. "
    "Las citas deben verificarse en las fuentes originales (EUR-Lex, BOE)."
)


# ---------------------------------------------------------------------------
# DOCX export
# ---------------------------------------------------------------------------

def _build_docx(record_json: str, query: str) -> bytes:
    data: Any = json.loads(record_json)
    answer: str = str(data.get("answer", ""))
    citations: list[Any] = data.get("citations", [])
    metadata: dict[str, Any] = data.get("metadata", {})
    verification: dict[str, Any] | None = data.get("verification")

    doc = Document()

    # Cover / header
    title = doc.add_heading("Análisis jurídico asistido — lex-agents", level=0)
    title.runs[0].font.color.rgb = RGBColor(0x1A, 0x56, 0xDB)  # brand blue

    doc.add_paragraph(f"Consulta: {query}")
    doc.add_paragraph(f"Fecha: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    doc.add_paragraph(f"Modelo: {metadata.get('model', 'desconocido')}")
    doc.add_paragraph(f"Prompt version: {metadata.get('prompt_version', '-')}")

    # Disclaimer banner
    p = doc.add_paragraph()
    run = p.add_run(_DISCLAIMER)
    run.bold = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0xB4, 0x5A, 0x00)  # amber

    doc.add_heading("Análisis", level=1)
    doc.add_paragraph(answer)

    # Verification status
    if verification:
        status = verification.get("status", "unknown")
        doc.add_heading("Estado de verificación", level=2)
        doc.add_paragraph(
            f"Estado: {status.upper()}  |  "
            f"Claims verificados: {verification.get('claims_passed', 0)}/{verification.get('claims_total', 0)}  |  "
            f"Referencias rotas: {len(verification.get('broken_refs', []))}"
        )

    # Citations
    if citations:
        doc.add_heading("Referencias normativas", level=1)
        for i, cit in enumerate(citations, 1):
            doc.add_heading(f"[REF:{cit.get('index', i)}] {cit.get('hierarchy_path', '')}", level=3)
            doc.add_paragraph(f"Fuente: {cit.get('source_id', '')}")
            fragment = cit.get("fragment_text", "")
            if fragment:
                p = doc.add_paragraph(style="Quote")
                p.add_run(fragment[:1000])

    # Technical metadata
    doc.add_heading("Metadatos técnicos", level=1)
    doc.add_paragraph(f"Latencia: {metadata.get('latency_ms', '-')} ms")
    doc.add_paragraph(f"Coste estimado: ${metadata.get('cost_estimate_usd', 0):.4f}")

    # Footer disclaimer on last paragraph
    doc.add_paragraph()
    doc.add_paragraph(_DISCLAIMER)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


@router.get("/{trace_id}/export")
async def export_consultation(
    trace_id: str,
    _user: CurrentUser = Depends(require_auth),
    store: ConsultationStore = Depends(get_store),
) -> StreamingResponse:
    """Export a consultation as a .docx file."""
    record = await store.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Consultation {trace_id!r} not found")

    docx_bytes = _build_docx(record.response_json, record.query)
    filename = f"analisis_{trace_id[:8]}_{datetime.now(UTC).strftime('%Y%m%d')}.docx"

    logger.info("consultation_exported", trace_id=trace_id, format="docx")
    return StreamingResponse(
        BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    issue_type: str  # error_factual | cita_incorrecta | fuera_de_alcance | otro
    description: str
    answer_excerpt: str = ""


@router.post("/{trace_id}/feedback", status_code=201)
async def submit_feedback(
    trace_id: str,
    body: FeedbackRequest,
    _user: CurrentUser = Depends(require_auth),
    store: ConsultationStore = Depends(get_store),
) -> dict[str, str]:
    """Save user feedback about a consultation to evals/feedback/."""
    record = await store.get(trace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Consultation {trace_id!r} not found")

    feedback_dir = Path("evals/feedback")
    feedback_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    filename = feedback_dir / f"{ts}_{trace_id[:8]}.json"

    payload = {
        "trace_id": trace_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "issue_type": body.issue_type,
        "description": body.description,
        "query": record.query,
        "answer_excerpt": body.answer_excerpt[:500],
    }
    filename.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("feedback_saved", trace_id=trace_id, issue_type=body.issue_type, path=str(filename))
    return {"status": "saved", "path": str(filename)}
