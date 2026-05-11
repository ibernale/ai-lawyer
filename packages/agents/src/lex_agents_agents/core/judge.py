"""Judge agent — evaluates Maker output against the Planner's DefinitionOfDone."""

from __future__ import annotations

import json
import time
from typing import Literal

import structlog
from opentelemetry import trace

from lex_agents_shared.anthropic_client import AnthropicClientWrapper, MODEL_OPUS

from lex_agents_agents.base_agent import AgentResponse
from lex_agents_agents.prompt_loader import load_prompt
from lex_agents_agents.shared.definition_of_done import DefinitionOfDone, JudgeVerdict

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_JUDGE_TOOL = {
    "name": "judge_response",
    "description": "Evaluate the Maker response against the Definition of Done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["publish", "revise", "reject"],
            },
            "scores": {
                "type": "object",
                "properties": {
                    "factual_support": {"type": "number", "minimum": 0, "maximum": 1},
                    "completeness": {"type": "number", "minimum": 0, "maximum": 1},
                    "jurisdictional_correctness": {"type": "number", "minimum": 0, "maximum": 1},
                    "caveat_appropriateness": {"type": "number", "minimum": 0, "maximum": 1},
                    "internal_consistency": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "factual_support", "completeness", "jurisdictional_correctness",
                    "caveat_appropriateness", "internal_consistency",
                ],
            },
            "gaps": {"type": "array", "items": {"type": "string"}},
            "iteration_brief": {"type": "string"},
        },
        "required": ["verdict", "scores", "gaps", "iteration_brief"],
    },
}

_MAX_ITERATIONS = 2


class LegalJudge:
    def __init__(
        self,
        client: AnthropicClientWrapper,
        prompt_version: int = 1,
    ) -> None:
        self._client = client
        self._cfg = load_prompt("judge", version=prompt_version)
        logger.info(
            "judge_prompt_loaded",
            version=self._cfg.version,
            hash=self._cfg.content_hash[:12],
        )

    def judge(
        self,
        responses: list[AgentResponse],
        dod: DefinitionOfDone,
        iteration: int = 1,
    ) -> JudgeVerdict:
        """Evaluate Maker responses against the DoD.

        If iteration >= _MAX_ITERATIONS and verdict is 'revise', forces 'publish'
        with verification_partial flag to prevent infinite loops.
        """
        with tracer.start_as_current_span("judge.evaluate") as span:
            span.set_attribute("judge.iteration", iteration)
            span.set_attribute("model", MODEL_OPUS)

            combined_answer = "\n\n---\n\n".join(r.answer_text for r in responses)

            user_content = self._build_user_content(combined_answer, dod)

            t0 = time.monotonic()
            try:
                resp = self._client.messages_create(
                    model=self._cfg.model,
                    max_tokens=self._cfg.max_tokens,
                    system=self._cfg.body,
                    tools=[_JUDGE_TOOL],
                    tool_choice={"type": "any"},
                    messages=[{"role": "user", "content": user_content}],
                )
            except Exception:
                logger.exception("judge_api_error", iteration=iteration)
                return self._force_publish(iteration, reason="api_error")

            latency = (time.monotonic() - t0) * 1000
            span.set_attribute("latency_ms", round(latency))

            tool_block = next(
                (b for b in resp.content if b.type == "tool_use"), None
            )
            if tool_block is None:
                logger.warning("judge_no_tool_use", iteration=iteration)
                return self._force_publish(iteration, reason="no_tool_use")

            try:
                raw: dict = (
                    tool_block.input  # type: ignore[union-attr]
                    if isinstance(tool_block.input, dict)  # type: ignore[union-attr]
                    else json.loads(tool_block.input)  # type: ignore[union-attr]
                )
                verdict_raw: Literal["publish", "revise", "reject"] = raw["verdict"]
                verdict = JudgeVerdict(
                    verdict=verdict_raw,
                    scores=raw.get("scores", {}),
                    gaps=raw.get("gaps", []),
                    iteration_brief=raw.get("iteration_brief", ""),
                    iteration=iteration,
                )
            except Exception:
                logger.exception("judge_parse_error", iteration=iteration)
                return self._force_publish(iteration, reason="parse_error")

            # Circuit breaker: cap at _MAX_ITERATIONS
            if iteration >= _MAX_ITERATIONS and verdict.verdict == "revise":
                logger.warning(
                    "judge_iteration_cap_reached",
                    iteration=iteration,
                    original_verdict="revise",
                )
                verdict = JudgeVerdict(
                    verdict="publish",
                    scores=verdict.scores,
                    gaps=verdict.gaps,
                    iteration_brief=(
                        f"[verification_partial=True] Máximo de iteraciones alcanzado. "
                        f"Brechas pendientes: {'; '.join(verdict.gaps)}"
                    ),
                    iteration=iteration,
                )

            logger.info(
                "judge_verdict",
                verdict=verdict.verdict,
                scores=verdict.scores,
                n_gaps=len(verdict.gaps),
                iteration=iteration,
                latency_ms=round(latency),
            )
            return verdict

    @staticmethod
    def _build_user_content(answer: str, dod: DefinitionOfDone) -> str:
        lines = [
            "## Respuesta del Maker\n",
            answer,
            "\n\n## Definition of Done\n",
        ]
        if dod.must_cover_concepts:
            lines.append(f"**Conceptos obligatorios:** {', '.join(dod.must_cover_concepts)}")
        if dod.must_consider_jurisdictions:
            lines.append(
                f"**Jurisdicciones obligatorias:** {', '.join(dod.must_consider_jurisdictions)}"
            )
        if dod.must_address_caveats:
            lines.append(f"**Cautelas requeridas:** {', '.join(dod.must_address_caveats)}")
        if dod.out_of_scope:
            lines.append(f"**Fuera de alcance (no incluir):** {', '.join(dod.out_of_scope)}")
        return "\n".join(lines)

    @staticmethod
    def _force_publish(iteration: int, reason: str) -> JudgeVerdict:
        return JudgeVerdict(
            verdict="publish",
            scores={
                "factual_support": 0.5,
                "completeness": 0.5,
                "jurisdictional_correctness": 0.5,
                "caveat_appropriateness": 0.5,
                "internal_consistency": 0.5,
            },
            gaps=[f"judge_unavailable:{reason}"],
            iteration_brief="",
            iteration=iteration,
            is_fallback=True,
        )
