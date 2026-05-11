"""BaseJudge — abstract base for all LDP evaluation judges.

Each concrete judge calls the Anthropic API once per LDP, evaluating all
five quality dimensions in a single tool-use call.
"""

from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar

import structlog
from lex_agents_shared.anthropic_client import AnthropicClientWrapper

try:
    from lex_agents_agents.prompt_loader import load_prompt
except ImportError:  # pragma: no cover — may not be installed in eval env
    load_prompt = None  # type: ignore[assignment]

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool schema — all 5 dimensions + overall + reasoning
# ---------------------------------------------------------------------------

_DIMENSION_ENUM = {"type": "string", "enum": ["supported", "partial", "unsupported"]}

JUDGE_TOOL: dict = {
    "name": "judge_ldp",
    "description": (
        "Evalúa un Legal Data Point (LDP) en cinco dimensiones de calidad y "
        "emite un veredicto global. Cada dimensión se valora como: "
        "'supported' (correcto y completo), 'partial' (parcialmente correcto "
        "o incompleto) o 'unsupported' (incorrecto o ausente)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "factual_support": {
                **_DIMENSION_ENUM,
                "description": (
                    "¿El texto de la afirmación tiene base factual verificable "
                    "en las fuentes citadas o en los chunks de contexto?"
                ),
            },
            "normative_accuracy": {
                **_DIMENSION_ENUM,
                "description": (
                    "¿La interpretación jurídica es defendible bajo la norma "
                    "aplicable (reglamento, directiva, ley, circular)?"
                ),
            },
            "jurisdictional_correctness": {
                **_DIMENSION_ENUM,
                "description": (
                    "¿Se aplica la jurisdicción correcta (ES / EU / UK / global)? "
                    "¿No se confunden normas nacionales con comunitarias?"
                ),
            },
            "completeness_partial": {
                **_DIMENSION_ENUM,
                "description": (
                    "¿Omite información relevante que cambiaría la conclusión "
                    "o la haría materialmente incompleta?"
                ),
            },
            "caveat_appropriateness": {
                **_DIMENSION_ENUM,
                "description": (
                    "¿Incluye las cautelas necesarias para ambigüedades normativas, "
                    "transposiciones pendientes o excepciones relevantes?"
                ),
            },
            "overall": {
                **_DIMENSION_ENUM,
                "description": (
                    "Veredicto global del LDP considerando todas las dimensiones."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Razonamiento conciso (≤ 150 palabras) que justifica cada "
                    "dimensión y el veredicto global. Cita fragmentos de texto "
                    "relevantes cuando sea posible."
                ),
            },
        },
        "required": [
            "factual_support",
            "normative_accuracy",
            "jurisdictional_correctness",
            "completeness_partial",
            "caveat_appropriateness",
            "overall",
            "reasoning",
        ],
    },
}

# ---------------------------------------------------------------------------
# Data classes (also re-exported by __init__.py for external consumers)
# ---------------------------------------------------------------------------

_FALLBACK_DIM = "partial"
_PARTIAL_DIMS: dict[str, str] = {
    "factual_support": _FALLBACK_DIM,
    "normative_accuracy": _FALLBACK_DIM,
    "jurisdictional_correctness": _FALLBACK_DIM,
    "completeness_partial": _FALLBACK_DIM,
    "caveat_appropriateness": _FALLBACK_DIM,
}


@dataclass(frozen=True)
class JudgeDimensions:
    """Scores for the five evaluation dimensions."""

    factual_support: str  # "supported" | "partial" | "unsupported"
    normative_accuracy: str
    jurisdictional_correctness: str
    completeness_partial: str
    caveat_appropriateness: str

    def as_dict(self) -> dict[str, str]:
        return {
            "factual_support": self.factual_support,
            "normative_accuracy": self.normative_accuracy,
            "jurisdictional_correctness": self.jurisdictional_correctness,
            "completeness_partial": self.completeness_partial,
            "caveat_appropriateness": self.caveat_appropriateness,
        }


@dataclass(frozen=True)
class SingleJudgeVerdict:
    """Verdict from a single LDP judge."""

    judge_id: str
    model: str
    ldp_id: str
    dimensions: JudgeDimensions
    overall: str  # "supported" | "partial" | "unsupported"
    reasoning: str
    is_fallback: bool = False
    fallback_reason: str = ""

    def passed(self) -> bool:
        """True when overall is 'supported'."""
        return self.overall == "supported"

    def failed(self) -> bool:
        """True when overall is 'unsupported'."""
        return self.overall == "unsupported"


# ---------------------------------------------------------------------------
# Minimal fallback system body (used when prompt file is not found)
# ---------------------------------------------------------------------------

_FALLBACK_SYSTEM_BODY = (
    "Eres un juez jurídico especializado en regulación bancaria UE/ES. "
    "Evalúa el Legal Data Point proporcionado usando la herramienta judge_ldp. "
    "Sé riguroso, conciso y justifica cada dimensión con evidencia del contexto."
)

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseJudge(ABC):
    """Abstract base for all LDP evaluation judges.

    Concrete subclasses must declare:
        judge_id: ClassVar[str]     — e.g. "A", "B", "C"
        model: ClassVar[str]        — Anthropic model identifier
        temperature: ClassVar[float] = 0.0
        prompt_version_key: ClassVar[str]  — "A" or "B" (selects prompt variant)
    """

    judge_id: ClassVar[str]
    model: ClassVar[str]
    temperature: ClassVar[float] = 0.0
    prompt_version_key: ClassVar[str] = "A"

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client
        self._system_body = self._load_system_body()

    # ------------------------------------------------------------------
    # Prompt loading
    # ------------------------------------------------------------------

    def _load_system_body(self) -> str:
        prompt_name = f"lemaj/judge/v{self.prompt_version_key}"
        if load_prompt is None:
            logger.warning(
                "lemaj_judge_prompt_loader_unavailable",
                judge_id=self.judge_id,
                using="fallback",
            )
            return _FALLBACK_SYSTEM_BODY

        try:
            cfg = load_prompt(prompt_name, version=1)
            logger.info(
                "lemaj_judge_prompt_loaded",
                judge_id=self.judge_id,
                prompt=prompt_name,
                hash=cfg.content_hash[:12],
            )
            return cfg.body
        except FileNotFoundError:
            logger.warning(
                "lemaj_judge_prompt_not_found",
                judge_id=self.judge_id,
                prompt=prompt_name,
                using="fallback",
            )
            return _FALLBACK_SYSTEM_BODY
        except Exception:
            logger.exception(
                "lemaj_judge_prompt_load_error",
                judge_id=self.judge_id,
                prompt=prompt_name,
                using="fallback",
            )
            return _FALLBACK_SYSTEM_BODY

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        ldp_id: str,
        claim_text: str,
        claim_type: str,
        supporting_refs: list[str],
        jurisdiction_scope: str,
        context: str,
        context_chunks: str,
    ) -> SingleJudgeVerdict:
        """Evaluate a single LDP across all five dimensions.

        Parameters
        ----------
        ldp_id:
            Unique identifier for the Legal Data Point.
        claim_text:
            The atomic legal claim to evaluate.
        claim_type:
            One of: factual / interpretive / procedural / cautionary.
        supporting_refs:
            List of [REF:n] citation identifiers from the original response.
        jurisdiction_scope:
            Jurisdiction tag, e.g. "ES", "EU", "ES+EU", "global", "unknown".
        context:
            The parent paragraph or surrounding text from the original response.
        context_chunks:
            Raw retrieved chunks used as grounding context (concatenated text).
        """
        user_content = self._build_user_content(
            ldp_id=ldp_id,
            claim_text=claim_text,
            claim_type=claim_type,
            supporting_refs=supporting_refs,
            jurisdiction_scope=jurisdiction_scope,
            context=context,
            context_chunks=context_chunks,
        )

        try:
            resp = self._client.messages_create(
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
                system=self._system_body,
                tools=[JUDGE_TOOL],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception:
            logger.exception(
                "lemaj_judge_api_error",
                judge_id=self.judge_id,
                ldp_id=ldp_id,
            )
            return self._fallback_verdict(
                judge_id=self.judge_id,
                model=self.model,
                ldp_id=ldp_id,
                reason="api_error",
            )

        tool_block = next(
            (b for b in resp.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            logger.warning(
                "lemaj_judge_no_tool_use",
                judge_id=self.judge_id,
                ldp_id=ldp_id,
            )
            return self._fallback_verdict(
                judge_id=self.judge_id,
                model=self.model,
                ldp_id=ldp_id,
                reason="no_tool_use_block",
            )

        try:
            raw: dict = (
                tool_block.input  # type: ignore[union-attr]
                if isinstance(tool_block.input, dict)  # type: ignore[union-attr]
                else json.loads(tool_block.input)  # type: ignore[union-attr]
            )
            dimensions = JudgeDimensions(
                factual_support=raw["factual_support"],
                normative_accuracy=raw["normative_accuracy"],
                jurisdictional_correctness=raw["jurisdictional_correctness"],
                completeness_partial=raw["completeness_partial"],
                caveat_appropriateness=raw["caveat_appropriateness"],
            )
            verdict = SingleJudgeVerdict(
                judge_id=self.judge_id,
                model=self.model,
                ldp_id=ldp_id,
                dimensions=dimensions,
                overall=raw["overall"],
                reasoning=raw.get("reasoning", ""),
            )
        except Exception:
            logger.exception(
                "lemaj_judge_parse_error",
                judge_id=self.judge_id,
                ldp_id=ldp_id,
            )
            return self._fallback_verdict(
                judge_id=self.judge_id,
                model=self.model,
                ldp_id=ldp_id,
                reason="parse_error",
            )

        logger.info(
            "lemaj_judge_verdict",
            judge_id=self.judge_id,
            ldp_id=ldp_id,
            overall=verdict.overall,
            factual=dimensions.factual_support,
            normative=dimensions.normative_accuracy,
            jurisdictional=dimensions.jurisdictional_correctness,
            completeness=dimensions.completeness_partial,
            caveat=dimensions.caveat_appropriateness,
        )
        return verdict

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_content(
        ldp_id: str,
        claim_text: str,
        claim_type: str,
        supporting_refs: list[str],
        jurisdiction_scope: str,
        context: str,
        context_chunks: str,
    ) -> str:
        refs_str = ", ".join(supporting_refs) if supporting_refs else "(ninguna)"
        return (
            f"## Legal Data Point a evaluar\n\n"
            f"**ID:** {ldp_id}\n"
            f"**Tipo:** {claim_type}\n"
            f"**Jurisdicción:** {jurisdiction_scope}\n"
            f"**Referencias de soporte:** {refs_str}\n\n"
            f"### Afirmación\n\n{claim_text}\n\n"
            f"### Contexto (párrafo original)\n\n{context}\n\n"
            f"### Chunks de contexto recuperados\n\n{context_chunks}\n\n"
            f"---\n\n"
            f"Evalúa el LDP usando la herramienta `judge_ldp`."
        )

    @staticmethod
    def _fallback_verdict(
        judge_id: str,
        model: str,
        ldp_id: str,
        reason: str,
    ) -> SingleJudgeVerdict:
        """Return a safe 'partial' verdict when the judge is unavailable."""
        return SingleJudgeVerdict(
            judge_id=judge_id,
            model=model,
            ldp_id=ldp_id,
            dimensions=JudgeDimensions(
                factual_support=_FALLBACK_DIM,
                normative_accuracy=_FALLBACK_DIM,
                jurisdictional_correctness=_FALLBACK_DIM,
                completeness_partial=_FALLBACK_DIM,
                caveat_appropriateness=_FALLBACK_DIM,
            ),
            overall=_FALLBACK_DIM,
            reasoning=f"[fallback:{reason}] El juez no pudo emitir veredicto.",
            is_fallback=True,
            fallback_reason=reason,
        )
