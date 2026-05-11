"""OrchestratorV2 — Planner/Maker/Judge pipeline with depth-based routing.

depth=shallow:  router_v1 → single specialist → verifier
depth=standard: planner  → maker(s) → verifier
depth=deep:     planner  → maker(s) → judge ↔ maker(s) (≤2 iter) → verifier
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from opentelemetry import trace
from pydantic import BaseModel, Field

from lex_agents_rag.assembler import ContextAssembler
from lex_agents_rag.query_rewriter import LegalQueryRewriter
from lex_agents_rag.reranker import BaseReranker
from lex_agents_rag.retriever import HybridRetriever, SearchFilters
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from lex_agents_shared.types import CitationMapping, VerificationReport

from lex_agents_agents.base_agent import AgentResponse, RoutingDecision
from lex_agents_agents.core.coordinator import CrossJurisdictionCoordinator
from lex_agents_agents.core.judge import LegalJudge
from lex_agents_agents.core.planner import LegalPlanner
from lex_agents_agents.routing.branch_classifier import get_specialist_class
from lex_agents_agents.routing.router_v1 import QueryRouter
from lex_agents_agents.shared.definition_of_done import BranchTask, PlannerOutput

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_OUT_OF_SCOPE_ANSWER = (
    "La consulta planteada está fuera del ámbito de este sistema, "
    "que cubre regulación bancaria (UE+ES+UK), protección de datos (RGPD), "
    "derecho laboral, mercantil societario, penal económico y administrativo. "
    "Para otras materias, consulte los servicios jurídicos especializados correspondientes."
)


class ConsultRequest(BaseModel):
    query: str
    jurisdiction_hint: str | None = None
    output_type: str | None = None
    depth: Literal["shallow", "standard", "deep"] | None = None


class ConsultResponse(BaseModel):
    trace_id: str
    answer: str
    citations: list[CitationMapping]
    verification: VerificationReport | None
    query_rewritten: str
    routing: dict[str, Any]
    metadata: dict[str, Any]
    # PMJ metadata
    depth_used: str = "standard"
    iterations: int = 0
    planner_output: dict[str, Any] | None = None
    judge_verdict: dict[str, Any] | None = None
    cost_breakdown_by_agent: dict[str, float] = Field(default_factory=dict)


@dataclass
class OrchestratorDeps:
    retriever: HybridRetriever
    reranker: BaseReranker
    query_rewriter: LegalQueryRewriter
    assembler: ContextAssembler
    client: AnthropicClientWrapper
    verifier: Any | None = None
    rag_top_k: int = 10


class OrchestratorV2:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self._deps = deps
        self._router = QueryRouter(deps.client)
        self._planner = LegalPlanner(deps.client)
        self._judge = LegalJudge(deps.client)
        self._coordinator = CrossJurisdictionCoordinator(deps.client)

    async def run(self, req: ConsultRequest) -> ConsultResponse:
        trace_id = str(uuid.uuid4())
        log = logger.bind(trace_id=trace_id)
        depth = req.depth or "standard"

        with tracer.start_as_current_span("orchestrator_v2.run") as root_span:
            root_span.set_attribute("trace_id", trace_id)
            root_span.set_attribute("depth", depth)
            t_total = time.monotonic()

            if depth == "shallow":
                result = await self._run_shallow(req, trace_id, log)
            elif depth == "standard":
                result = await self._run_standard(req, trace_id, log)
            else:
                result = await self._run_deep(req, trace_id, log)

            total_ms = round((time.monotonic() - t_total) * 1000)
            root_span.set_attribute("latency_ms", total_ms)
            result.metadata["latency_ms"] = total_ms
            log.info("orchestrator_v2_complete", depth=depth, latency_ms=total_ms)
            return result

    # ── Shallow path ────────────────────────────────────────────────────────

    async def _run_shallow(
        self, req: ConsultRequest, trace_id: str, log: Any
    ) -> ConsultResponse:
        decision: RoutingDecision
        with tracer.start_as_current_span("orchestrator_v2.route"):
            decision = self._router.route(req.query)
            log.info("shallow_routing", branch=decision.branch)

        if decision.branch == "fuera_de_alcance":
            return self._out_of_scope(trace_id, req.query, "shallow")

        assembled, rewritten = await self._rag(req, decision.jurisdictions)
        specialist_cls = get_specialist_class(decision.branch)
        specialist = specialist_cls(self._deps.client)
        agent_resp = await specialist.run_async(rewritten.expanded_query, assembled, trace_id)

        verification = await self._verify(trace_id, agent_resp, assembled)
        agent_resp.verification = verification

        return self._build_response(
            trace_id=trace_id,
            final=agent_resp,
            decision=decision,
            depth_used="shallow",
        )

    # ── Standard path ───────────────────────────────────────────────────────

    async def _run_standard(
        self, req: ConsultRequest, trace_id: str, log: Any
    ) -> ConsultResponse:
        plan = self._planner.plan(
            req.query, req.jurisdiction_hint, req.output_type, depth_hint="standard"
        )

        if self._is_out_of_scope(plan):
            return self._out_of_scope(trace_id, req.query, "standard", plan)

        decision = self._plan_to_routing(plan)
        assembled, rewritten = await self._rag(req, plan.jurisdictions)

        if len(plan.sub_tasks) <= 1:
            task = plan.sub_tasks[0] if plan.sub_tasks else BranchTask(
                id="T1", branch=decision.branch, priority=1, weight=1.0,
                query=rewritten.expanded_query,
            )
            specialist_cls = get_specialist_class(task.branch)
            specialist = specialist_cls(self._deps.client)
            agent_resp = await specialist.run_async(
                rewritten.expanded_query, assembled, trace_id, sub_task=task
            )
        else:
            responses = await self._coordinator.run_parallel(
                plan.sub_tasks, assembled, trace_id
            )
            agent_resp = self._coordinator.synthesize(responses, plan, trace_id)

        verification = await self._verify(trace_id, agent_resp, assembled)
        agent_resp.verification = verification

        return self._build_response(
            trace_id=trace_id,
            final=agent_resp,
            decision=decision,
            depth_used="standard",
            planner_output=plan,
        )

    # ── Deep path ────────────────────────────────────────────────────────────

    async def _run_deep(
        self, req: ConsultRequest, trace_id: str, log: Any
    ) -> ConsultResponse:
        plan = self._planner.plan(
            req.query, req.jurisdiction_hint, req.output_type, depth_hint="deep"
        )

        if self._is_out_of_scope(plan):
            return self._out_of_scope(trace_id, req.query, "deep", plan)

        decision = self._plan_to_routing(plan)
        assembled, rewritten = await self._rag(req, plan.jurisdictions)

        iterations = 0
        judge_verdict_dict: dict[str, Any] | None = None
        cost_breakdown: dict[str, float] = {}

        current_query = rewritten.expanded_query
        final_resp: AgentResponse | None = None
        responses: list[AgentResponse] = []

        for iteration in range(1, 3):  # max 2 iterations
            iterations = iteration

            if len(plan.sub_tasks) <= 1:
                task = plan.sub_tasks[0] if plan.sub_tasks else BranchTask(
                    id="T1", branch=decision.branch, priority=1, weight=1.0,
                    query=current_query,
                )
                specialist_cls = get_specialist_class(task.branch)
                specialist = specialist_cls(self._deps.client)
                responses = [await specialist.run_async(
                    current_query, assembled, trace_id, sub_task=task
                )]
            else:
                responses = await self._coordinator.run_parallel(
                    plan.sub_tasks, assembled, trace_id
                )

            # Judge
            verdict = self._judge.judge(responses, plan.definition_of_done, iteration)
            judge_verdict_dict = {
                "verdict": verdict.verdict,
                "scores": verdict.scores,
                "gaps": verdict.gaps,
                "iteration_brief": verdict.iteration_brief,
                "iteration": verdict.iteration,
            }

            # Accumulate costs
            for resp in responses:
                branch = getattr(resp.metadata, "prompt_name", f"branch_{iteration}")
                cost_breakdown[branch] = cost_breakdown.get(branch, 0.0) + resp.metadata.cost_estimate_usd

            if verdict.verdict in ("publish", "reject"):
                if len(responses) > 1:
                    final_resp = self._coordinator.synthesize(responses, plan, trace_id)
                else:
                    final_resp = responses[0]
                break

            # revise → update query with judge brief and loop
            current_query = f"{rewritten.expanded_query}\n\n[REVISIÓN REQUERIDA]: {verdict.iteration_brief}"
            log.info("deep_iteration_revise", iteration=iteration)

        if final_resp is None:
            if responses:
                final_resp = responses[0] if len(responses) == 1 else self._coordinator.synthesize(responses, plan, trace_id)  # type: ignore[possibly-undefined]
            else:
                return self._out_of_scope(trace_id, req.query, "deep", plan)

        verification = await self._verify(trace_id, final_resp, assembled)
        final_resp.verification = verification

        return self._build_response(
            trace_id=trace_id,
            final=final_resp,
            decision=decision,
            depth_used="deep",
            planner_output=plan,
            judge_verdict=judge_verdict_dict,
            iterations=iterations,
            cost_breakdown=cost_breakdown,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    async def _rag(
        self, req: ConsultRequest, jurisdictions: list[str]
    ) -> tuple[Any, Any]:
        with tracer.start_as_current_span("orchestrator_v2.rag"):
            rewritten = self._deps.query_rewriter.rewrite(req.query)
            filters = SearchFilters(
                jurisdiction=req.jurisdiction_hint or (jurisdictions[0] if jurisdictions else None),
                status="vigente",
            )
            chunks = self._deps.retriever.search(rewritten.expanded_query, filters)
            reranked = self._deps.reranker.rerank(
                rewritten.expanded_query, chunks, top_k=self._deps.rag_top_k
            )
            assembled = self._deps.assembler.assemble(reranked)
        return assembled, rewritten

    async def _verify(
        self, trace_id: str, agent_resp: AgentResponse, assembled: Any
    ) -> VerificationReport | None:
        if self._deps.verifier is None:
            return None
        with tracer.start_as_current_span("orchestrator_v2.verify"):
            chunk_store = {m.chunk_id: m.fragment_text for m in assembled.citation_mapping}
            return await self._deps.verifier.run(
                response_id=trace_id,
                answer_text=agent_resp.answer_text,
                citations=assembled.citation_mapping,
                chunk_store=chunk_store,
            )

    @staticmethod
    def _is_out_of_scope(plan: PlannerOutput) -> bool:
        branches = [b["name"] for b in plan.branches]
        return branches == ["fuera_de_alcance"] or not plan.sub_tasks

    @staticmethod
    def _plan_to_routing(plan: PlannerOutput) -> RoutingDecision:
        primary = plan.branches[0] if plan.branches else {"name": "fuera_de_alcance"}
        return RoutingDecision(
            branch=str(primary.get("name", "fuera_de_alcance")),
            jurisdictions=plan.jurisdictions,
            output_type=plan.output_type,
            depth=plan.depth,
        )

    @staticmethod
    def _out_of_scope(
        trace_id: str,
        query: str,
        depth: str,
        plan: PlannerOutput | None = None,
    ) -> ConsultResponse:
        return ConsultResponse(
            trace_id=trace_id,
            answer=_OUT_OF_SCOPE_ANSWER,
            citations=[],
            verification=None,
            query_rewritten=query,
            routing={"branch": "fuera_de_alcance"},
            metadata={},
            depth_used=depth,
            planner_output=None,
        )

    @staticmethod
    def _build_response(
        trace_id: str,
        final: AgentResponse,
        decision: RoutingDecision,
        depth_used: str,
        planner_output: PlannerOutput | None = None,
        judge_verdict: dict[str, Any] | None = None,
        iterations: int = 0,
        cost_breakdown: dict[str, float] | None = None,
    ) -> ConsultResponse:
        meta = final.metadata
        return ConsultResponse(
            trace_id=trace_id,
            answer=final.answer_text,
            citations=final.citations,
            verification=final.verification,
            query_rewritten=final.query_rewritten,
            routing={
                "branch": decision.branch,
                "jurisdictions": decision.jurisdictions,
                "output_type": decision.output_type,
                "depth": decision.depth,
            },
            metadata={
                "prompt_name": meta.prompt_name,
                "prompt_version": meta.prompt_version,
                "prompt_hash": meta.prompt_hash[:12],
                "model": meta.model,
                "input_tokens": meta.input_tokens,
                "output_tokens": meta.output_tokens,
                "cost_estimate_usd": meta.cost_estimate_usd,
            },
            depth_used=depth_used,
            iterations=iterations,
            planner_output=(
                {
                    "branches": planner_output.branches,
                    "jurisdictions": planner_output.jurisdictions,
                    "output_type": planner_output.output_type,
                    "depth": planner_output.depth,
                    "sub_tasks": [
                        {"id": t.id, "branch": t.branch, "weight": t.weight}
                        for t in planner_output.sub_tasks
                    ],
                }
                if planner_output
                else None
            ),
            judge_verdict=judge_verdict,
            cost_breakdown_by_agent=cost_breakdown or {},
        )
