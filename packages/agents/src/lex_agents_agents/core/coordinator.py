"""Cross-jurisdiction coordinator — runs Makers in parallel and synthesizes output."""

from __future__ import annotations

import asyncio
import time

import structlog
from lex_agents_rag.assembler import AssembledContext
from lex_agents_shared.anthropic_client import MODEL_OPUS, AnthropicClientWrapper
from lex_agents_shared.types import CitationMapping
from opentelemetry import trace

from lex_agents_agents.base_agent import AgentMetadata, AgentResponse
from lex_agents_agents.core.comparative_synthesizer import ComparativeSynthesizer
from lex_agents_agents.prompt_loader import load_prompt
from lex_agents_agents.routing.branch_classifier import get_specialist_class
from lex_agents_agents.shared.definition_of_done import BranchTask, PlannerOutput

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class CrossJurisdictionCoordinator:
    """Executes multiple Maker specialists in parallel and synthesizes their outputs.

    EU > national hierarchy is respected: when both cover the same aspect, the
    EU-law position prevails and is marked with [EU-PREF].
    Contradictions between branches are flagged inline as ⚠️ DISCREPANCIA NORMATIVA.
    """

    def __init__(
        self,
        client: AnthropicClientWrapper,
        synthesis_prompt_version: int = 2,
    ) -> None:
        self._client = client
        try:
            self._synthesis_cfg = load_prompt("sintesis", version=synthesis_prompt_version)
        except FileNotFoundError:
            self._synthesis_cfg = load_prompt("sintesis", version=1)

    async def run_parallel(
        self,
        tasks: list[BranchTask],
        assembled: AssembledContext,
        trace_id: str,
    ) -> list[AgentResponse]:
        """Execute all branch tasks concurrently and return ordered responses."""
        with tracer.start_as_current_span("coordinator.run_parallel") as span:
            span.set_attribute("n_tasks", len(tasks))
            sorted_tasks = sorted(tasks, key=lambda t: t.priority)

            async def _run_one(task: BranchTask) -> AgentResponse:
                cls = get_specialist_class(task.branch)
                specialist = cls(self._client)
                return await specialist.run_async(
                    query=task.query,
                    assembled=assembled,
                    trace_id=trace_id,
                    sub_task=task,
                )

            raw_results = await asyncio.gather(
                *[_run_one(t) for t in sorted_tasks],
                return_exceptions=True,
            )
            responses: list[AgentResponse] = []
            n_failed = 0
            for i, result in enumerate(raw_results):
                if isinstance(result, BaseException):
                    n_failed += 1
                    logger.error(
                        "coordinator_specialist_failed",
                        branch=sorted_tasks[i].branch,
                        error=str(result),
                        exc_info=result,
                    )
                else:
                    responses.append(result)
            if not responses:
                raise RuntimeError("All specialist branches failed; cannot synthesize.")
            if n_failed > 0:
                # Partial failure: log clearly so degraded response is visible in traces
                logger.warning(
                    "coordinator_partial_failure",
                    n_failed=n_failed,
                    n_ok=len(responses),
                    total=len(sorted_tasks),
                )
            logger.info("coordinator_parallel_done", n_responses=len(responses))
            return responses

    async def synthesize_comparative(
        self,
        responses: list[AgentResponse],
        planner_output: PlannerOutput,
        trace_id: str,
    ) -> AgentResponse:
        """Produce a ComparativeResponse for analisis_comparativo output_type (ADR 0027).

        Returns an AgentResponse whose comparative_output field is populated.
        The answer_text field contains a short prose summary for backward-compat clients.
        """
        comparative_synthesizer = ComparativeSynthesizer(self._client)
        comparative = await comparative_synthesizer.synthesize(responses, planner_output, trace_id)

        # Build a brief prose summary for clients that only read answer_text.
        juris_str = ", ".join(comparative.jurisdictions_compared)
        n_dims = len(comparative.dimensions)
        n_divs = len(comparative.divergences)
        summary = (
            f"Análisis comparativo: {comparative.issue}\n\n"
            f"Jurisdicciones: {juris_str} · {n_dims} dimensiones · {n_divs} divergencias.\n\n"
            "Consulte el campo comparative_output para la tabla completa."
        )

        merged_citations = self._merge_citations(responses)
        return AgentResponse(
            trace_id=trace_id,
            answer_text=summary,
            citations=merged_citations,
            verification=None,
            metadata=responses[0].metadata,
            query_rewritten=responses[0].query_rewritten,
            comparative_output=comparative,
        )

    def synthesize(
        self,
        responses: list[AgentResponse],
        planner_output: PlannerOutput,
        trace_id: str,
    ) -> AgentResponse:
        """Merge multi-branch responses into one unified AgentResponse.

        Uses LLM synthesis prompt when multiple branches are present.
        Falls back to single-response pass-through for one branch.
        """
        if len(responses) == 1:
            return responses[0]

        with tracer.start_as_current_span("coordinator.synthesize") as span:
            span.set_attribute("n_responses", len(responses))

            branch_names = [t.branch for t in planner_output.sub_tasks]
            task_weights = {t.branch: t.weight for t in planner_output.sub_tasks}

            user_content = self._build_synthesis_prompt(responses, branch_names, task_weights)

            t0 = time.monotonic()
            try:
                resp = self._client.messages_create(
                    model=MODEL_OPUS,
                    max_tokens=self._synthesis_cfg.max_tokens,
                    system=self._synthesis_cfg.body,
                    messages=[{"role": "user", "content": user_content}],
                )
                answer_text: str = resp.content[0].text  # type: ignore[union-attr]
                in_tok = resp.usage.input_tokens
                out_tok = resp.usage.output_tokens
            except Exception:
                logger.exception("coordinator_synthesis_api_error")
                # Fallback: concatenate with clear separators
                answer_text = self._fallback_merge(responses, branch_names)
                in_tok = out_tok = 0

            latency = (time.monotonic() - t0) * 1000
            span.set_attribute("latency_ms", round(latency))

            # Merge all citations, renumber sequentially
            merged_citations = self._merge_citations(responses)

            cost_per_m_in, cost_per_m_out = 15.0, 75.0
            cost = (in_tok / 1_000_000 * cost_per_m_in) + (out_tok / 1_000_000 * cost_per_m_out)

            logger.info(
                "coordinator_synthesis_done",
                n_branches=len(responses),
                latency_ms=round(latency),
            )

            return AgentResponse(
                trace_id=trace_id,
                answer_text=answer_text,
                citations=merged_citations,
                verification=None,
                metadata=AgentMetadata(
                    trace_id=trace_id,
                    prompt_name=self._synthesis_cfg.name,
                    prompt_version=self._synthesis_cfg.version,
                    prompt_hash=self._synthesis_cfg.content_hash,
                    model=MODEL_OPUS,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    latency_ms=latency,
                    cost_estimate_usd=cost,
                ),
                query_rewritten=responses[0].query_rewritten,
            )

    @staticmethod
    def _build_synthesis_prompt(
        responses: list[AgentResponse],
        branch_names: list[str],
        weights: dict[str, float],
    ) -> str:
        parts = ["# Respuestas de los especialistas por rama\n"]
        for _, (resp, name) in enumerate(zip(responses, branch_names, strict=False)):
            w = weights.get(name, 1.0 / len(responses))
            parts.append(
                f"\n## RAMA: {name} (peso: {w:.2f})\n\n{resp.answer_text}\n"
            )
        parts.append(
            "\n---\nSintetiza las respuestas anteriores en un único dictamen integrado. "
            "Respeta la jerarquía EU > derecho nacional. Marca [EU-PREF] cuando la norma UE "
            "prevalezca y ⚠️ DISCREPANCIA NORMATIVA cuando haya contradicción real entre ramas."
        )
        return "".join(parts)

    @staticmethod
    def _fallback_merge(responses: list[AgentResponse], branch_names: list[str]) -> str:
        sections = []
        for resp, name in zip(responses, branch_names, strict=False):
            sections.append(f"## Análisis: {name}\n\n{resp.answer_text}")
        return "\n\n---\n\n".join(sections)

    @staticmethod
    def _merge_citations(responses: list[AgentResponse]) -> list[CitationMapping]:
        """Merge and renumber citations from all branch responses sequentially."""
        merged: list[CitationMapping] = []
        new_index = 1
        seen: set[str] = set()
        for resp in responses:
            for cit in resp.citations:
                key = f"{cit.source_id}:{cit.chunk_id}"
                if key not in seen:
                    seen.add(key)
                    merged.append(
                        CitationMapping(
                            index=new_index,
                            chunk_id=cit.chunk_id,
                            source_id=cit.source_id,
                            hierarchy_path=cit.hierarchy_path,
                            fragment_text=cit.fragment_text,
                        )
                    )
                    new_index += 1
        return merged
