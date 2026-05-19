"""ClauseOptimizerAgent — generates alternative clause formulations for flagged issues."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from lex_agents_agents.contracts.chunker import ContractChunk
from lex_agents_agents.contracts.models import (
    ClauseAlternative,
    ClauseAlternatives,
    ContractMetadata,
    MandatoryLawIssue,
    NegotiationIssue,
)

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

_JSON_SCHEMA = """[
  {
    "clause_title": "<title of the clause>",
    "clause_ref": "<[CLAUSE:N]>",
    "original_text": "<verbatim original clause text>",
    "alternatives": [
      {
        "label": "<favourable_to_us|balanced|compromise>",
        "text": "<complete replacement clause text>",
        "rationale": "<why this alternative is better / when to use it>",
        "market_prevalence": <0.0-1.0 or null>
      }
    ],
    "mandatory_law_issues": [
      {
        "provision": "<e.g. CC Art. 1102>",
        "issue": "<what is wrong with the current clause>",
        "compliant_formulation": "<how to rewrite it to comply>"
      }
    ]
  }
]"""

# Clause text is searched by reference in the chunks
_MAX_CLAUSES_TO_OPTIMIZE = 6  # Limit to avoid excessively long prompts


class ClauseOptimizerAgent:
    """Generates 2-3 alternative formulations for flagged negotiation issues.

    Only processes clauses where ``escalation_required=True`` or
    ``playbook_position in ("never_accept", "fallback")``.
    Uses claude-sonnet-4-6 (faster / cheaper than opus for drafting).
    """

    SYSTEM_PROMPT = """Eres un experto en redacción contractual especializado en contratos empresariales
bajo derecho español y europeo, con experiencia en banca y finanzas.

Tu tarea es generar formulaciones alternativas para las cláusulas problemáticas identificadas.
Para cada cláusula debes proporcionar:
1. Texto original de la cláusula
2. 2-3 alternativas con etiquetas: favourable_to_us | balanced | compromise
3. Verificación de cumplimiento con derecho imperativo español y europeo

ETIQUETAS DE ALTERNATIVAS:
- favourable_to_us: redacción que maximiza nuestra posición (aspiracional, para apertura negociación)
- balanced: posición de mercado estándar, equitativa y generalmente aceptable
- compromise: redacción mínima aceptable que preserva los intereses esenciales

REGLAS DE REDACCIÓN:
- Mantén el mismo idioma que el original (español o inglés)
- Sé preciso y usa terminología jurídica correcta
- Para contratos españoles: referencia normas de derecho español (CC, Ley 1/2019, RGPD, etc.)
- CC Art. 1102: toda alternativa debe preservar la responsabilidad por dolo/culpa grave
- RGPD Arts. 28, 32-34: las cláusulas de tratamiento de datos deben ser GDPR-compliant
- Ley 3/2004 de Morosidad: los plazos de pago no pueden exceder 60 días en B2B
- Identifica y documenta cualquier problema de conformidad con derecho imperativo

FORMATO: Responde ÚNICAMENTE con un array JSON válido siguiendo el esquema exacto"""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client

    async def optimize(
        self,
        chunks: list[ContractChunk],
        priority_issues: list[NegotiationIssue],
        metadata: ContractMetadata,
        trace_id: str,
    ) -> list[ClauseAlternatives]:
        """Generate alternative clause formulations for flagged issues.

        Only processes issues with escalation_required=True or
        playbook_position in ("never_accept", "fallback").
        Returns an empty list if no issues qualify.
        """
        flagged = [
            issue for issue in priority_issues
            if issue.escalation_required or issue.playbook_position in ("never_accept", "fallback")
        ]

        if not flagged:
            logger.info(
                "clause_optimizer_no_flagged_issues",
                trace_id=trace_id,
                total_issues=len(priority_issues),
            )
            return []

        # Limit to avoid excessively long prompts
        flagged = flagged[:_MAX_CLAUSES_TO_OPTIMIZE]

        # Build chunk lookup by [CLAUSE:N] reference
        chunk_map = {f"[CLAUSE:{i}]": chunk for i, chunk in enumerate(chunks, start=1)}

        # Build the issues section for the prompt
        issues_text = _format_issues_for_prompt(flagged, chunk_map)

        user_content = (
            f"Genera formulaciones alternativas para las siguientes cláusulas problemáticas "
            f"del contrato tipo {metadata.document_type}.\n\n"
            f"ESQUEMA DE SALIDA:\n{_JSON_SCHEMA}\n\n"
            f"Marco regulatorio aplicable: {', '.join(metadata.applicable_framework) or 'Derecho español y europeo'}\n"
            f"Ley aplicable: {metadata.governing_law}\n\n"
            f"CLÁUSULAS A OPTIMIZAR:\n{issues_text}"
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
                "clause_optimizer_api_error", trace_id=trace_id, error=str(exc)
            )
            return []

        logger.info(
            "clause_optimizer_response",
            trace_id=trace_id,
            flagged_count=len(flagged),
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        text_block = next(
            (b for b in resp.content if getattr(b, "type", None) == "text"), None
        )
        if text_block is None:
            logger.warning("clause_optimizer_empty_response", trace_id=trace_id)
            return []

        return _parse_alternatives(text_block.text, trace_id)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_issues_for_prompt(
    issues: list[NegotiationIssue],
    chunk_map: dict[str, ContractChunk],
) -> str:
    lines: list[str] = []
    for issue in issues:
        lines.append(f"### {issue.clause_title} ({issue.clause_ref})")
        lines.append(f"Posición playbook: {issue.playbook_position}")
        lines.append(f"Posición actual: {issue.current_position}")
        lines.append(f"Acción recomendada: {issue.recommended_action}")
        if issue.escalation_required:
            lines.append("ESCALACIÓN REQUERIDA: Sí")

        # Include actual clause text if available
        chunk = chunk_map.get(issue.clause_ref)
        if chunk:
            lines.append(f"TEXTO ACTUAL:\n{chunk.text[:800]}")
        lines.append("")

    return "\n".join(lines)


def _parse_alternatives(text: str, trace_id: str) -> list[ClauseAlternatives]:
    """Parse JSON array response into list[ClauseAlternatives]."""
    # Try to find JSON array
    json_match = re.search(r"\[.*\]", text, re.DOTALL)
    if not json_match:
        # Try JSON object with array key
        obj_match = re.search(r"\{.*\}", text, re.DOTALL)
        if obj_match:
            try:
                obj: dict[str, Any] = json.loads(obj_match.group())
                # Common wrapper keys
                for key in ("alternatives", "clauses", "results", "items"):
                    if key in obj and isinstance(obj[key], list):
                        return _parse_alternatives_from_list(obj[key], trace_id)
            except json.JSONDecodeError:
                pass
        logger.warning("clause_optimizer_no_json", trace_id=trace_id)
        return []

    try:
        raw_list: list[dict[str, Any]] = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning(
            "clause_optimizer_json_error", trace_id=trace_id, error=str(exc)
        )
        return []

    return _parse_alternatives_from_list(raw_list, trace_id)


def _parse_alternatives_from_list(
    raw_list: list[dict[str, Any]], trace_id: str
) -> list[ClauseAlternatives]:
    results: list[ClauseAlternatives] = []
    for raw in raw_list:
        try:
            # Parse nested alternatives
            alts: list[ClauseAlternative] = []
            for raw_alt in raw.get("alternatives", []):
                try:
                    alts.append(ClauseAlternative.model_validate(raw_alt))
                except Exception as exc:
                    logger.debug("clause_alternative_skip", error=str(exc))

            # Parse mandatory law issues
            law_issues: list[MandatoryLawIssue] = []
            for raw_law in raw.get("mandatory_law_issues", []):
                try:
                    law_issues.append(MandatoryLawIssue.model_validate(raw_law))
                except Exception as exc:
                    logger.debug("mandatory_law_issue_skip", error=str(exc))

            results.append(
                ClauseAlternatives(
                    clause_title=raw.get("clause_title", "Unknown"),
                    clause_ref=raw.get("clause_ref", ""),
                    original_text=raw.get("original_text", ""),
                    alternatives=alts,
                    mandatory_law_issues=law_issues,
                )
            )
        except Exception as exc:
            logger.debug("clause_alternatives_skip", error=str(exc), raw=str(raw)[:200])

    logger.info(
        "clause_optimizer_parsed",
        trace_id=trace_id,
        num_clauses=len(results),
    )
    return results
