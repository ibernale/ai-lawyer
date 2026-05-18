"""RiskAnalystAgent — multi-dimensional risk analysis at clause level."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from lex_agents_agents.contracts.chunker import ContractChunk
from lex_agents_agents.contracts.models import ContractMetadata, RiskAssessment, RiskFactor

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Cost constants for claude-opus-4-7 (deep reasoning model)
_INPUT_TOKEN_COST_PER_M = 15.0
_OUTPUT_TOKEN_COST_PER_M = 75.0

_RISK_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 4096

_JSON_SCHEMA = """{
  "overall_score": <0.0-1.0>,
  "overall_rating": "<green|yellow|red|critical>",
  "factors": [
    {
      "category": "<financial|legal|operational|strategic>",
      "issue": "<descripción clara del problema>",
      "severity": "<low|medium|high|critical>",
      "confidence": <0.0-1.0>,
      "clause_refs": ["[CLAUSE:N]", ...],
      "remediation": "<recomendación concreta>"
    }
  ]
}"""


class RiskAnalystAgent:
    """Multi-dimensional risk analysis at clause level."""

    SYSTEM_PROMPT = """Eres un experto en análisis de riesgo contractual especializado en contratos empresariales
bajo derecho español y europeo, con experiencia en banca y finanzas.

Tu tarea es analizar cada cláusula del contrato e identificar factores de riesgo en cuatro dimensiones:
- FINANCIERO: riesgos económicos, caps de responsabilidad, condiciones de pago, penalizaciones
- LEGAL: cláusulas abusivas, conflictos con ley imperativa, ambigüedades interpretativas
- OPERACIONAL: obligaciones de difícil cumplimiento, plazos irrealistas, requisitos técnicos
- ESTRATÉGICO: compromisos de exclusividad, restricciones de competencia, impacto reputacional

Para cada factor de riesgo identifica:
- Categoría (financial|legal|operational|strategic)
- Descripción clara del problema
- Severidad: low|medium|high|critical
  * critical: incumplimiento podría generar litigios/sanciones graves o pérdidas mayores
  * high: riesgo significativo que debe negociarse o mitigarse
  * medium: riesgo moderado, vigilar en ejecución
  * low: riesgo menor, documentar pero no bloquea
- Nivel de confianza (0.0-1.0)
- Referencias a las cláusulas donde se detecta el riesgo (ej: "[CLAUSE:3]", "[CLAUSE:7]")
- Recomendación concreta de remediación

IMPORTANTE:
- Cita SIEMPRE la(s) cláusula(s) fuente de cada riesgo
- No inventes riesgos; si una sección está bien redactada, no la incluyas
- Prioriza riesgos críticos y altos; incluye los medios/bajos si son relevantes
- Para contratos bancarios, presta especial atención a: limitaciones de responsabilidad,
  cláusulas de incumplimiento cruzado (cross-default), cambio material adverso (MAC),
  garantías y representaciones, y cumplimiento regulatorio (CRR, AML, GDPR)

Calcula también:
- overall_score: score global de riesgo de 0.0 (sin riesgo) a 1.0 (riesgo extremo)
- overall_rating: green (<0.3) | yellow (0.3-0.6) | red (0.6-0.85) | critical (>0.85)

Responde ÚNICAMENTE con un JSON válido siguiendo el esquema proporcionado."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    async def analyze(
        self,
        chunks: list[ContractChunk],
        metadata: ContractMetadata,
        trace_id: str,
    ) -> RiskAssessment:
        """Analyze all contract chunks for risk factors.

        Formats chunks with [CLAUSE:N] references for the model to cite.
        Uses claude-opus-4-7 for deep reasoning.
        """
        clause_text = _format_chunks_for_prompt(chunks)
        framework_hint = (
            f"Marco regulatorio aplicable: {', '.join(metadata.applicable_framework)}"
            if metadata.applicable_framework
            else ""
        )

        user_content = (
            f"Analiza los siguientes cláusulas del contrato tipo "
            f"{metadata.document_type} y devuelve el JSON de riesgo:\n\n"
            f"ESQUEMA:\n{_JSON_SCHEMA}\n\n"
            f"{framework_hint}\n\n"
            f"CLÁUSULAS:\n{clause_text}"
        )

        try:
            resp = self._client.messages_create(
                model=_RISK_MODEL,
                max_tokens=_MAX_TOKENS,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as exc:
            logger.exception(
                "risk_analyst_api_error", trace_id=trace_id, error=str(exc)
            )
            return _fallback_risk_assessment()

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = (in_tok / 1_000_000 * _INPUT_TOKEN_COST_PER_M) + (
            out_tok / 1_000_000 * _OUTPUT_TOKEN_COST_PER_M
        )
        logger.info(
            "risk_analyst_response",
            trace_id=trace_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("risk_analyst_empty_response", trace_id=trace_id)
            return _fallback_risk_assessment()

        return _parse_risk_assessment(text_block.text, trace_id)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_chunks_for_prompt(chunks: list[ContractChunk]) -> str:
    """Format chunks as numbered clause blocks for the LLM prompt."""
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[CLAUSE:{i}] {chunk.clause_path}"
        if chunk.clause_title and chunk.clause_title != chunk.clause_path:
            header += f" — {chunk.clause_title}"
        lines.append(f"{header}\n{chunk.text}")
    return "\n\n".join(lines)


def _parse_risk_assessment(text: str, trace_id: str) -> RiskAssessment:
    """Parse JSON response into RiskAssessment; fall back on failure."""
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        logger.warning("risk_analyst_no_json", trace_id=trace_id)
        return _fallback_risk_assessment()

    try:
        data: dict[str, Any] = json.loads(json_match.group())
        return RiskAssessment.model_validate(data)
    except Exception as exc:
        logger.warning(
            "risk_analyst_parse_error", trace_id=trace_id, error=str(exc)
        )
        # Attempt partial recovery
        try:
            return _partial_risk_assessment(data if "data" in dir() else {})
        except Exception:
            return _fallback_risk_assessment()


def _partial_risk_assessment(data: dict[str, Any]) -> RiskAssessment:
    """Build a best-effort RiskAssessment from a partially-valid dict."""
    raw_factors: list[dict[str, Any]] = data.get("factors", [])
    factors: list[RiskFactor] = []
    for f in raw_factors:
        try:
            factors.append(RiskFactor.model_validate(f))
        except Exception as exc:
            logger.debug("risk_factor_parse_skip", error=str(exc))
            continue

    score = float(data.get("overall_score", 0.5))
    rating = data.get("overall_rating", "yellow")
    if rating not in ("green", "yellow", "red", "critical"):
        rating = _score_to_rating(score)

    return RiskAssessment(
        overall_score=score,
        overall_rating=rating,
        factors=factors,
    )


def _fallback_risk_assessment() -> RiskAssessment:
    """Fallback when the LLM cannot produce a valid response."""
    return RiskAssessment(
        overall_score=0.5,
        overall_rating="yellow",
        factors=[
            RiskFactor(
                category="legal",
                issue="No se pudo completar el análisis de riesgo automático.",
                severity="medium",
                confidence=0.0,
                clause_refs=[],
                remediation="Revisar manualmente el contrato con asesoría jurídica especializada.",
            )
        ],
    )


def _score_to_rating(score: float) -> str:
    if score < 0.3:
        return "green"
    if score < 0.6:
        return "yellow"
    if score < 0.85:
        return "red"
    return "critical"
