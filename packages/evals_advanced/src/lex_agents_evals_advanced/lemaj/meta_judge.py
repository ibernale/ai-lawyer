"""MetaJudge — arbitrates disagreements among the 3-judge panel.

Called only when the three panel judges do not agree on `overall`.
Outputs a final verdict or `review_required` when confidence is low.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import structlog

from lex_agents_shared.anthropic_client import AnthropicClientWrapper, MODEL_OPUS

from lex_agents_evals_advanced.types import LegalDataPoint, SingleJudgeVerdict

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_FALLBACK_SYSTEM = (
    "Eres el meta-juez del sistema LeMAJ. Recibes los veredictos de tres jueces "
    "sobre un Legal Data Point y debes emitir el veredicto final. "
    "Si la evidencia es insuficiente o los razonamientos son contradictorios, "
    "usa 'review_required'. Responde SOLO con JSON: "
    '{"final_verdict": "supported|partial|unsupported|review_required", '
    '"low_confidence": bool, "reasoning": "string"}.'
)

_META_TOOL: dict = {
    "name": "meta_judge_verdict",
    "description": (
        "Emite el veredicto final del meta-juez tras analizar los tres veredictos "
        "del panel. Usa 'review_required' si la evidencia es insuficiente o los "
        "razonamientos son fundamentalmente contradictorios."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "final_verdict": {
                "type": "string",
                "enum": ["supported", "partial", "unsupported", "review_required"],
                "description": "Veredicto final consolidado.",
            },
            "low_confidence": {
                "type": "boolean",
                "description": (
                    "True si la normativa es ambigua, falta contexto determinante, "
                    "o los tres jueces dan razonamientos irreconciliables."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Justificación del veredicto final (≤ 200 palabras). "
                    "Explica qué jueces se ponderan más y por qué."
                ),
            },
        },
        "required": ["final_verdict", "low_confidence", "reasoning"],
    },
}


def _load_meta_system() -> str:
    prompt_path = Path("docs/prompts/lemaj/meta_judge/v1.md")
    if prompt_path.exists():
        text = prompt_path.read_text()
        # Strip YAML frontmatter if present
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return text.strip()
    logger.warning("meta_judge_prompt_not_found", path=str(prompt_path), using="fallback")
    return _FALLBACK_SYSTEM


def _format_verdicts_block(verdicts: list[SingleJudgeVerdict]) -> str:
    lines = []
    for v in verdicts:
        lines.append(
            f"### Juez {v.judge_id} ({v.model})\n"
            f"- Factual: {v.dimensions.factual_support}\n"
            f"- Normativo: {v.dimensions.normative_accuracy}\n"
            f"- Jurisdiccional: {v.dimensions.jurisdictional_correctness}\n"
            f"- Completitud: {v.dimensions.completeness_partial}\n"
            f"- Cautelas: {v.dimensions.caveat_appropriateness}\n"
            f"- **Overall:** {v.overall}\n"
            f"- Razonamiento: {v.reasoning[:300]}"
        )
    return "\n\n".join(lines)


class MetaJudge:
    """Arbitrates LDP verdicts when the 3-judge panel disagrees."""

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client
        self._system = _load_meta_system()

    async def arbitrate(
        self,
        ldp: LegalDataPoint,
        verdicts: list[SingleJudgeVerdict],
    ) -> tuple[Literal["supported", "partial", "unsupported", "review_required"], str]:
        """Arbitrate disagreeing panel verdicts.

        Returns (final_verdict, reasoning).
        Falls back to 'review_required' on any API or parse failure.
        """
        verdict_block = _format_verdicts_block(verdicts)
        user_content = (
            f"## Legal Data Point en disputa\n\n"
            f"**ID:** {ldp.ldp_id}\n"
            f"**Tipo:** {ldp.claim_type}\n"
            f"**Jurisdicción:** {ldp.jurisdiction_scope}\n\n"
            f"### Afirmación\n\n{ldp.claim_text}\n\n"
            f"### Contexto\n\n{ldp.context[:500]}\n\n"
            f"## Veredictos del panel\n\n{verdict_block}\n\n"
            "---\n\n"
            "Emite el veredicto final usando la herramienta `meta_judge_verdict`."
        )

        try:
            resp = self._client.messages_create(
                model=MODEL_OPUS,
                max_tokens=512,
                temperature=0.0,
                system=self._system,
                tools=[_META_TOOL],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception:
            logger.exception("meta_judge_api_error", ldp_id=ldp.ldp_id)
            return "review_required", "Meta-judge API error — requires human review."

        tool_block = next(
            (b for b in resp.content if b.type == "tool_use"), None  # type: ignore[union-attr]
        )
        if tool_block is None:
            logger.warning("meta_judge_no_tool_use", ldp_id=ldp.ldp_id)
            return "review_required", "Meta-judge returned no tool_use block."

        try:
            raw: dict = (
                tool_block.input  # type: ignore[union-attr]
                if isinstance(tool_block.input, dict)  # type: ignore[union-attr]
                else json.loads(tool_block.input)  # type: ignore[union-attr]
            )
            verdict_str = raw.get("final_verdict", "review_required")
            low_confidence = bool(raw.get("low_confidence", False))
            reasoning = raw.get("reasoning", "")

            if low_confidence or verdict_str not in ("supported", "partial", "unsupported"):
                final: Literal["supported", "partial", "unsupported", "review_required"] = (
                    "review_required"
                )
            else:
                final = verdict_str  # type: ignore[assignment]

            logger.info(
                "meta_judge_arbitrated",
                ldp_id=ldp.ldp_id,
                verdict=final,
                low_confidence=low_confidence,
            )
            return final, reasoning

        except Exception:
            logger.exception("meta_judge_parse_error", ldp_id=ldp.ldp_id)
            return "review_required", "Meta-judge parse error — requires human review."
