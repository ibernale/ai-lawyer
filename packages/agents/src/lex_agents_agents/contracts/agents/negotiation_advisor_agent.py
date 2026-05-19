"""NegotiationAdvisorAgent — evaluates contract clauses against playbook positions."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from lex_agents_agents.contracts.chunker import ContractChunk
from lex_agents_agents.contracts.models import (
    ContractMetadata,
    NegotiationIssue,
    NegotiationScenario,
    NegotiationSummary,
    RiskAssessment,
)
from lex_agents_agents.contracts.playbook_loader import get_playbook_summary

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 4096

# Cost constants for claude-opus-4-7
_INPUT_TOKEN_COST_PER_M = 15.0
_OUTPUT_TOKEN_COST_PER_M = 75.0

_JSON_SCHEMA = """{
  "posture_score": <0.0-1.0, 0=fully favourable, 1=fully unfavourable>,
  "posture_label": "<reject|renegotiate|conditionally_accept|accept>",
  "priority_issues": [
    {
      "clause_title": "<title of the clause>",
      "clause_ref": "<[CLAUSE:N]>",
      "current_position": "<brief description of what the clause actually says>",
      "playbook_position": "<preferred|acceptable|fallback|never_accept|uncharted>",
      "market_percentile": <0.0-1.0, 0=favourable to us, 1=very unfavourable>,
      "recommended_action": "<concrete negotiation action>",
      "alternative_language": "<suggested replacement clause text or null>",
      "escalation_required": <true|false>
    }
  ],
  "scenarios": {
    "accept_as_is": {
      "label": "Aceptar como está",
      "risk_summary": "<summary of risks if signed as-is>",
      "residual_risks": ["<risk 1>", "<risk 2>"],
      "target_clauses": [],
      "expected_outcome": "<outcome>",
      "walk_away_conditions": ["<condition>"]
    },
    "renegotiate_priority": {
      "label": "Renegociar aspectos prioritarios",
      "risk_summary": "<summary>",
      "residual_risks": ["<risk>"],
      "target_clauses": ["[CLAUSE:N]"],
      "expected_outcome": "<outcome>",
      "walk_away_conditions": ["<condition>"]
    },
    "full_renegotiation": {
      "label": "Renegociación completa",
      "risk_summary": "<summary>",
      "residual_risks": [],
      "target_clauses": ["[CLAUSE:N]"],
      "expected_outcome": "<outcome>",
      "walk_away_conditions": []
    }
  },
  "playbook_version": "1.0.0",
  "benchmark_sources": ["<source 1>", "<source 2>"]
}"""


class NegotiationAdvisorAgent:
    """Evaluates contract clauses against internal playbook positions.

    Uses claude-opus-4-7 for deep reasoning. Loads the relevant playbook
    via PlaybookLoader and includes a compact summary in the prompt.
    """

    SYSTEM_PROMPT = """Eres un experto en negociación contractual en el sector bancario español y europeo,
con profundo conocimiento de las posiciones estándar de mercado (LMA, ISDA, EDPB) y del
derecho contractual español (Código Civil, Ley 1/2019, RGPD).

Tu tarea es analizar cada cláusula sustantiva del contrato y:
1. Identificar su posición actual respecto al playbook interno
2. Asignar un percentil de mercado (0.0 = muy favorable para nosotros, 1.0 = muy desfavorable)
3. Determinar si la posición es: preferred | acceptable | fallback | never_accept | uncharted
4. Recomendar una acción de negociación concreta
5. Proporcionar texto alternativo cuando sea útil
6. Identificar si requiere escalada a Legal o Comité de Riesgo

Para la postura global:
- reject (0.75-1.0): múltiples cláusulas never_accept o riesgo crítico irreparable
- renegotiate (0.50-0.75): cláusulas fallback o escalación requerida; negociación necesaria
- conditionally_accept (0.25-0.50): posición subóptima pero sin deal-breakers
- accept (0.0-0.25): posición favorable o aceptable en todos los puntos materiales

Para los tres escenarios:
- accept_as_is: análisis de riesgos residuales si se firma sin cambios
- renegotiate_priority: enfocarse en las 2-3 cláusulas más críticas
- full_renegotiation: plan completo con todas las cláusulas a mejorar

REGLAS:
- Cita SIEMPRE la cláusula fuente con [CLAUSE:N]
- Basa tu análisis en el playbook proporcionado; si no hay playbook, usa criterios de mercado
- Para contratos bancarios españoles: CC Art. 1102 prohíbe excluir responsabilidad por dolo
- Para contratos con componente GDPR: RGPD Arts. 28, 32-34 son normas imperativas
- Sé concreto en las recomendaciones; no uses vaguedades como "revisar" sin especificar qué
- Responde ÚNICAMENTE con JSON válido siguiendo el esquema proporcionado"""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    async def advise(
        self,
        chunks: list[ContractChunk],
        metadata: ContractMetadata,
        risk: RiskAssessment,
        trace_id: str,
        party_role: str | None = None,
    ) -> NegotiationSummary:
        """Evaluate the contract against playbook positions and return NegotiationSummary.

        ``party_role`` defaults to the first party's role in metadata if not provided.
        """
        # Resolve party role
        resolved_role = party_role or _detect_party_role(metadata)

        # Load playbook summary (compact, truncated for prompt)
        playbook_summary = get_playbook_summary(metadata.document_type, resolved_role)

        # Format contract chunks
        clause_text = _format_chunks_for_prompt(chunks)

        # Build risk context (top 3 factors)
        top_risks = "\n".join(
            f"- [{f.severity.upper()}] {f.issue} ({f.clause_refs})"
            for f in sorted(risk.factors, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.severity, 9))[:3]
        )
        risk_context = (
            f"RIESGO GLOBAL: {risk.overall_rating.upper()} ({risk.overall_score:.2f})\n"
            f"TOP RIESGOS:\n{top_risks}" if top_risks else f"RIESGO: {risk.overall_rating}"
        )

        user_content = (
            f"Evalúa la posición negociadora del contrato tipo {metadata.document_type}, "
            f"perspectiva {resolved_role}.\n\n"
            f"ESQUEMA DE SALIDA:\n{_JSON_SCHEMA}\n\n"
            f"{playbook_summary}\n\n"
            f"CONTEXTO DE RIESGO:\n{risk_context}\n\n"
            f"CLÁUSULAS DEL CONTRATO:\n{clause_text}"
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
                "negotiation_advisor_api_error", trace_id=trace_id, error=str(exc)
            )
            return _fallback_summary()

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = (in_tok / 1_000_000 * _INPUT_TOKEN_COST_PER_M) + (
            out_tok / 1_000_000 * _OUTPUT_TOKEN_COST_PER_M
        )
        logger.info(
            "negotiation_advisor_response",
            trace_id=trace_id,
            party_role=resolved_role,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round(cost, 6),
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("negotiation_advisor_empty_response", trace_id=trace_id)
            return _fallback_summary()

        return _parse_summary(text_block.text, trace_id)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_party_role(metadata: ContractMetadata) -> str:
    """Infer the bank's party role from metadata parties list.

    Falls back to 'lender' for LoanAgreement, 'controller' for DPA, etc.
    """
    # Try to detect from party names containing 'Santander' or 'banco'
    for party in metadata.parties:
        name_lower = party.name.lower()
        if any(kw in name_lower for kw in ("santander", "banco", "bank", "caixa", "bbva", "sabadell")):
            return party.role

    # Default roles per contract type
    defaults: dict[str, str] = {
        "LoanAgreement": "lender",
        "CreditFacility": "lender",
        "NDA": "disclosing",
        "ServiceAgreement": "client",
        "MSA": "client",
        "SLA": "client",
        "DataProcessingAgreement": "controller",
        "ISDA": "lender",
        "Guarantee": "lender",
        "EmploymentContract": "employer",
    }
    return defaults.get(metadata.document_type, "client")


def _format_chunks_for_prompt(chunks: list[ContractChunk]) -> str:
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        header = f"[CLAUSE:{i}] {chunk.clause_path}"
        if chunk.clause_title and chunk.clause_title != chunk.clause_path:
            header += f" — {chunk.clause_title}"
        lines.append(f"{header}\n{chunk.text}")
    return "\n\n".join(lines)


def _parse_summary(text: str, trace_id: str) -> NegotiationSummary:
    """Parse JSON response into NegotiationSummary; fall back on failure."""
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not json_match:
        logger.warning("negotiation_advisor_no_json", trace_id=trace_id)
        return _fallback_summary()

    try:
        data: dict[str, Any] = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning(
            "negotiation_advisor_json_error", trace_id=trace_id, error=str(exc)
        )
        return _fallback_summary()

    # Parse priority issues
    issues: list[NegotiationIssue] = []
    for raw in data.get("priority_issues", []):
        try:
            issues.append(NegotiationIssue.model_validate(raw))
        except Exception as exc:
            logger.debug("negotiation_issue_skip", error=str(exc))

    # Parse scenarios
    scenarios: dict[str, NegotiationScenario] = {}
    for key, raw_scenario in data.get("scenarios", {}).items():
        try:
            scenarios[key] = NegotiationScenario.model_validate(raw_scenario)
        except Exception as exc:
            logger.debug("negotiation_scenario_skip", key=key, error=str(exc))

    # Ensure mandatory scenarios exist
    for scenario_key, default_label in (
        ("accept_as_is", "Aceptar como está"),
        ("renegotiate_priority", "Renegociar aspectos prioritarios"),
        ("full_renegotiation", "Renegociación completa"),
    ):
        if scenario_key not in scenarios:
            scenarios[scenario_key] = NegotiationScenario(
                label=default_label,
                risk_summary="Análisis no disponible.",
            )

    posture_score = float(data.get("posture_score", 0.5))
    posture_label = data.get("posture_label", "conditionally_accept")
    if posture_label not in ("reject", "renegotiate", "conditionally_accept", "accept"):
        posture_label = _score_to_posture(posture_score)

    return NegotiationSummary(
        posture_score=posture_score,
        posture_label=posture_label,
        priority_issues=issues,
        scenarios=scenarios,
        playbook_version=data.get("playbook_version", "1.0.0"),
        benchmark_sources=data.get("benchmark_sources", []),
    )


def _score_to_posture(score: float) -> str:
    if score >= 0.75:
        return "reject"
    if score >= 0.50:
        return "renegotiate"
    if score >= 0.25:
        return "conditionally_accept"
    return "accept"


def _fallback_summary() -> NegotiationSummary:
    """Return a safe fallback NegotiationSummary when the LLM fails."""
    return NegotiationSummary(
        posture_score=0.5,
        posture_label="conditionally_accept",
        priority_issues=[],
        scenarios={
            "accept_as_is": NegotiationScenario(
                label="Aceptar como está",
                risk_summary="No se pudo completar el análisis de negociación automático.",
            ),
            "renegotiate_priority": NegotiationScenario(
                label="Renegociar aspectos prioritarios",
                risk_summary="No se pudo completar el análisis de negociación automático.",
            ),
            "full_renegotiation": NegotiationScenario(
                label="Renegociación completa",
                risk_summary="No se pudo completar el análisis de negociación automático.",
            ),
        },
        playbook_version="1.0.0",
        benchmark_sources=[],
    )
