"""ComplianceAgent — checks contract clauses against applicable regulatory frameworks."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from lex_agents_agents.contracts.chunker import ContractChunk
from lex_agents_agents.contracts.models import ComplianceFinding, ContractMetadata

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_JSON_SCHEMA = """{
  "findings": [
    {
      "regulation": "<norma específica, ej: GDPR Art. 28.3, CRR Art. 92, CC Art. 1102>",
      "status": "<compliant|non_compliant|requires_review|not_applicable>",
      "finding": "<descripción del hallazgo>",
      "clause_refs": ["[CLAUSE:N]", ...],
      "recommendation": "<acción recomendada o null si compliant>"
    }
  ]
}"""

# Compliance checks per framework, used to build focused prompts
_FRAMEWORK_CHECKS: dict[str, str] = {
    "GDPR": (
        "GDPR / RGPD:\n"
        "- Art. 28: cláusulas DPA mínimas (objeto, duración, naturaleza, finalidad, tipo de datos, "
        "obligaciones del encargado, derechos del interesado)\n"
        "- Art. 28.3: instrucciones documentadas por escrito\n"
        "- Art. 28.3(f): asistencia al responsable con ejercicio de derechos\n"
        "- Art. 28.3(h): supresión o devolución de datos al terminar\n"
        "- Art. 32: medidas de seguridad técnicas y organizativas\n"
        "- Art. 44-49: restricciones a transferencias internacionales\n"
        "- Art. 37: nombramiento DPO si procede\n"
        "Comprobar también conformidad con LOPDGDD (Ley Orgánica 3/2018)."
    ),
    "CRR": (
        "CRR (Reglamento UE 575/2013):\n"
        "- Art. 92: requisitos de capital mínimo — ¿hay cláusulas que comprometan ratios de capital?\n"
        "- Art. 394-403: grandes exposiciones — ¿hay concentración de riesgo sin límites?\n"
        "- Art. 416-428: liquidez — ¿hay compromisos de financiación que afecten LCR/NSFR?\n"
        "Comprobar si el contrato genera exposición no contemplada en el cálculo prudencial."
    ),
    "AML": (
        "AML / Ley 10/2010 LPBC:\n"
        "- Art. 3-4: diligencia debida — ¿identifica el contrato a las partes adecuadamente?\n"
        "- Art. 17: operaciones no presenciales — ¿hay salvaguardias suficientes?\n"
        "- Art. 26: conservación de documentación (10 años)\n"
        "Comprobar también conformidad con Directiva UE 2018/843 (5ª AMLD)."
    ),
    "CódigoCivil": (
        "Código Civil español:\n"
        "- Art. 1102: responsabilidad por dolo no puede limitarse — comprobar cláusulas "
        "de limitación de responsabilidad\n"
        "- Art. 1103: moderación de la pena por los tribunales\n"
        "- Art. 1255: límites a la autonomía de la voluntad (ley, moral, orden público)\n"
        "- Art. 1740-1757: requisitos del contrato de préstamo\n"
        "- Art. 1857-1886: garantías reales\n"
        "Cláusulas potencialmente nulas o abusivas bajo CC."
    ),
    "Ley7/1998": (
        "Ley 7/1998 LCGC (condiciones generales de la contratación):\n"
        "- Art. 8: cláusulas abusivas en contratos con consumidores\n"
        "- Comprobar condiciones predispuestas no negociadas individualmente\n"
        "- Transparencia y claridad en la redacción de cláusulas."
    ),
    "PSD2": (
        "PSD2 / PSD3 (Directiva de servicios de pago):\n"
        "- Art. 45-52: información precontractual en contratos de pago\n"
        "- Art. 73-77: responsabilidad del proveedor de servicios de pago\n"
        "- Art. 94-95: seguridad y autenticación reforzada."
    ),
    "EMIR": (
        "EMIR (Reglamento UE 648/2012):\n"
        "- Art. 11: gestión del riesgo operacional en derivados OTC\n"
        "- Requisitos de compensación central y reporting a registro de operaciones\n"
        "- Acuerdos de intercambio de garantías (collateral)."
    ),
}

# Default checks that apply to all contracts
_UNIVERSAL_CHECKS = (
    "Para TODOS los contratos, comprobar también:\n"
    "- Ley Orgánica 3/2018 (LOPDGDD): tratamiento de datos de empleados/terceros\n"
    "- RD-Ley 5/2023: litigación estratégica / whistleblowing si aplica\n"
    "- Cláusulas con posible conflicto con orden público o ley imperativa española\n"
    "- Cláusulas de elección de foro/ley que puedan ser inoponibles en España"
)


class ComplianceAgent:
    """Checks contract clauses against applicable regulatory frameworks.

    Uses the `applicable_framework` field from ContractMetadata to focus
    on relevant regulations. Always applies universal checks.

    Status values:
    - compliant: satisfies the requirement
    - non_compliant: violates a mandatory requirement
    - requires_review: ambiguous or conditional — needs lawyer review
    - not_applicable: regulation does not apply to this contract type
    """

    SYSTEM_PROMPT = """Eres un experto en compliance regulatorio para contratos en el sector bancario y financiero español,
con profundo conocimiento de derecho español, europeo, y regulación bancaria (BCE/BdE).

Tu tarea es revisar las cláusulas del contrato contra el marco regulatorio aplicable e identificar:
1. Cumplimiento de requisitos obligatorios (compliant)
2. Incumplimientos explícitos (non_compliant)
3. Áreas de ambigüedad que requieren revisión legal (requires_review)
4. Regulaciones claramente inaplicables al tipo de contrato (not_applicable)

Para cada hallazgo incluye:
- La norma específica con artículo (ej: "GDPR Art. 28.3(f)")
- El estado de cumplimiento
- Una descripción clara y factual del hallazgo
- Las cláusulas del contrato relevantes ([CLAUSE:N])
- Una recomendación concreta (solo si status ≠ compliant)

REGLAS:
- Cita SIEMPRE la norma específica, no la regulación en abstracto
- No marques como non_compliant si hay ambigüedad; usa requires_review
- Sé exhaustivo pero evita falsos positivos — la confianza es crítica en contexto bancario
- Para obligaciones de forma (escritura, notaría, registro): verificar explícitamente
- Para cláusulas inoponibles bajo ley imperativa española: marcar como non_compliant
  con referencia al artículo que las invalida (ej: CC Art. 1102 para limitación de dolo)

Responde ÚNICAMENTE con JSON válido siguiendo el esquema, sin texto adicional."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    async def check(
        self,
        chunks: list[ContractChunk],
        metadata: ContractMetadata,
        trace_id: str,
    ) -> list[ComplianceFinding]:
        """Run compliance checks against all applicable frameworks.

        Returns a list of ComplianceFinding sorted by severity
        (non_compliant first, then requires_review, then compliant).
        """
        clause_text = _format_chunks_for_prompt(chunks)
        framework_checks = _build_framework_checks(metadata.applicable_framework)

        user_content = (
            f"Revisa el contrato tipo {metadata.document_type} contra el marco regulatorio aplicable.\n\n"
            f"ESQUEMA DE SALIDA:\n{_JSON_SCHEMA}\n\n"
            f"MARCOS REGULATORIOS A REVISAR:\n{framework_checks}\n\n"
            f"CLÁUSULAS:\n{clause_text}"
        )

        try:
            resp = self._client.messages_create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:
            logger.exception(
                "compliance_agent_api_error", trace_id=trace_id, error=str(exc)
            )
            return _fallback_findings(metadata.applicable_framework)

        logger.info(
            "compliance_agent_response",
            trace_id=trace_id,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("compliance_agent_empty_response", trace_id=trace_id)
            return _fallback_findings(metadata.applicable_framework)

        return _parse_findings(text_block.text, trace_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_framework_checks(frameworks: list[str]) -> str:
    """Build the prompt section describing which regulatory checks to perform."""
    lines: list[str] = []
    for fw in frameworks:
        for key, text in _FRAMEWORK_CHECKS.items():
            if key.lower() in fw.lower() or fw.lower() in key.lower():
                lines.append(text)
                break
        else:
            lines.append(f"{fw}: revisar requisitos generales aplicables a este marco normativo.")
    lines.append(_UNIVERSAL_CHECKS)
    return "\n\n".join(lines)


def _format_chunks_for_prompt(chunks: list[ContractChunk]) -> str:
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[CLAUSE:{i}] {chunk.clause_path}"
        if chunk.clause_title and chunk.clause_title != chunk.clause_path:
            header += f" — {chunk.clause_title}"
        lines.append(f"{header}\n{chunk.text}")
    return "\n\n".join(lines)


def _parse_findings(text: str, trace_id: str) -> list[ComplianceFinding]:
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        logger.warning("compliance_agent_no_json", trace_id=trace_id)
        return []

    try:
        data: dict[str, Any] = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning("compliance_agent_json_error", trace_id=trace_id, error=str(exc))
        return []

    findings: list[ComplianceFinding] = []
    for raw in data.get("findings", []):
        try:
            findings.append(ComplianceFinding.model_validate(raw))
        except Exception as exc:
            logger.debug("compliance_finding_skip", error=str(exc), raw=raw)

    # Sort: non_compliant first, then requires_review, then compliant, then not_applicable
    _order = {"non_compliant": 0, "requires_review": 1, "compliant": 2, "not_applicable": 3}
    findings.sort(key=lambda f: _order.get(f.status, 99))

    logger.info("compliance_findings_parsed", trace_id=trace_id, num_findings=len(findings))
    return findings


def _fallback_findings(frameworks: list[str]) -> list[ComplianceFinding]:
    """Return a generic requires_review finding when the agent fails."""
    return [
        ComplianceFinding(
            regulation=f"{fw}: análisis no completado",
            status="requires_review",
            finding="No se pudo completar el análisis de compliance automático. Revisar manualmente.",
            clause_refs=[],
            recommendation="Realizar revisión manual con asesoramiento jurídico especializado.",
        )
        for fw in (frameworks or ["Marco regulatorio aplicable"])
    ]
