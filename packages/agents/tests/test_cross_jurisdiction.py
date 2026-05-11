"""Integration test — cross-jurisdiction: bancario + RGPD detects 2 branches (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lex_agents_agents.base_agent import AgentMetadata, AgentResponse
from lex_agents_agents.core.orchestrator_v2 import (
    ConsultRequest,
    ConsultResponse,
    OrchestratorDeps,
    OrchestratorV2,
)
from lex_agents_agents.shared.definition_of_done import (
    BranchTask,
    DefinitionOfDone,
    JudgeVerdict,
    PlannerOutput,
)


def _make_deps() -> OrchestratorDeps:
    retriever = MagicMock()
    retriever.search.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = []
    rewritten = MagicMock()
    rewritten.expanded_query = "transferencia datos bancarios EEUU"
    query_rewriter = MagicMock()
    query_rewriter.rewrite.return_value = rewritten
    assembled = MagicMock()
    assembled.context_text = "Contexto RGPD + CRR."
    assembled.citation_mapping = []
    assembler = MagicMock()
    assembler.assemble.return_value = assembled
    client = MagicMock()
    return OrchestratorDeps(
        retriever=retriever,
        reranker=reranker,
        query_rewriter=query_rewriter,
        assembler=assembler,
        client=client,
        verifier=None,
        rag_top_k=5,
    )


def _make_agent_response(trace_id: str, text: str) -> AgentResponse:
    return AgentResponse(
        trace_id=trace_id,
        answer_text=text,
        citations=[],
        verification=None,
        metadata=AgentMetadata(
            trace_id=trace_id,
            prompt_name="test",
            prompt_version=1,
            prompt_hash="abc",
            model="claude-opus-4-7",
            input_tokens=200,
            output_tokens=300,
            latency_ms=500.0,
            cost_estimate_usd=0.025,
        ),
        query_rewritten="transferencia datos bancarios EEUU",
    )


def _make_cross_jurisdiction_plan() -> PlannerOutput:
    """Plan for bancario+RGPD cross-jurisdiction query."""
    return PlannerOutput(
        branches=[
            {"name": "regulatorio_bancario_ue_es", "priority": 1, "weight": 0.6},
            {"name": "datos_personales_rgpd", "priority": 2, "weight": 0.4},
        ],
        jurisdictions=["EU", "ES", "US"],
        output_type="dictamen",
        depth="standard",
        sub_tasks=[
            BranchTask(id="T1", branch="regulatorio_bancario_ue_es", priority=1, weight=0.6,
                       query="requisitos prudenciales transferencia EEUU", expected_artifacts=["capital"]),
            BranchTask(id="T2", branch="datos_personales_rgpd", priority=2, weight=0.4,
                       query="base legal transferencia internacional datos", expected_artifacts=["sccs"]),
        ],
        definition_of_done=DefinitionOfDone(
            must_cover_concepts=["transferencia internacional", "CRR", "RGPD art 44"],
            must_consider_jurisdictions=["EU", "US"],
            must_address_caveats=["decisión de adecuación EEUU no vigente"],
            out_of_scope=["derecho penal"],
        ),
    )


@pytest.mark.asyncio
class TestCrossJurisdictionBancarioRgpd:
    async def test_two_branches_detected_via_planner(self) -> None:
        """Standard path with mocked planner returns two-branch plan, coordinator is called."""
        deps = _make_deps()

        with (
            patch("lex_agents_agents.core.orchestrator_v2.QueryRouter"),
            patch("lex_agents_agents.core.orchestrator_v2.LegalPlanner") as MockPlanner,
            patch("lex_agents_agents.core.orchestrator_v2.LegalJudge"),
            patch("lex_agents_agents.core.orchestrator_v2.CrossJurisdictionCoordinator") as MockCoord,
        ):
            plan = _make_cross_jurisdiction_plan()
            MockPlanner.return_value.plan.return_value = plan

            bancario_resp = _make_agent_response("t1", "Análisis CRR: requisito capital 8%.")
            rgpd_resp = _make_agent_response("t1", "Análisis RGPD: transferencia requiere SCCs art 46.")
            synth_resp = _make_agent_response("t1", "Dictamen integrado [EU-PREF]: CRR + RGPD.")
            MockCoord.return_value.run_parallel = AsyncMock(return_value=[bancario_resp, rgpd_resp])
            MockCoord.return_value.synthesize.return_value = synth_resp

            orch = OrchestratorV2(deps)
            query = (
                "Una entidad bancaria española transfiere datos de clientes a su filial en EEUU "
                "para gestión de riesgo de crédito. ¿Qué requisitos aplican?"
            )
            result = await orch.run(ConsultRequest(query=query, depth="standard"))

        assert isinstance(result, ConsultResponse)
        assert result.depth_used == "standard"
        assert result.planner_output is not None

        # Two branches must appear in planner output
        branch_names = [b["name"] for b in result.planner_output["branches"]]
        assert "regulatorio_bancario_ue_es" in branch_names
        assert "datos_personales_rgpd" in branch_names

        # Coordinator must have been invoked with 2 tasks
        orch._coordinator.run_parallel.assert_awaited_once()
        call_args = orch._coordinator.run_parallel.call_args
        tasks_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("tasks", [])
        assert len(tasks_arg) == 2

        orch._coordinator.synthesize.assert_called_once()
        assert result.answer == "Dictamen integrado [EU-PREF]: CRR + RGPD."

    async def test_deep_path_with_two_branches(self) -> None:
        """Deep path: planner detects 2 branches, judge publishes on first iteration."""
        deps = _make_deps()

        with (
            patch("lex_agents_agents.core.orchestrator_v2.QueryRouter"),
            patch("lex_agents_agents.core.orchestrator_v2.LegalPlanner") as MockPlanner,
            patch("lex_agents_agents.core.orchestrator_v2.LegalJudge") as MockJudge,
            patch("lex_agents_agents.core.orchestrator_v2.CrossJurisdictionCoordinator") as MockCoord,
        ):
            plan = _make_cross_jurisdiction_plan()
            plan.depth = "deep"
            MockPlanner.return_value.plan.return_value = plan

            bancario_resp = _make_agent_response("t2", "Ratio capital OK.")
            rgpd_resp = _make_agent_response("t2", "SCCs requeridos.")
            synth_resp = _make_agent_response("t2", "Integrado: capital + SCCs.")
            MockCoord.return_value.run_parallel = AsyncMock(return_value=[bancario_resp, rgpd_resp])
            MockCoord.return_value.synthesize.return_value = synth_resp

            publish_verdict = JudgeVerdict(
                verdict="publish",
                scores={"factual_support": 0.9, "completeness": 0.85, "jurisdictional_correctness": 0.9,
                        "caveat_appropriateness": 0.9, "internal_consistency": 0.95},
                gaps=[],
                iteration_brief="Dictamen completo.",
                iteration=1,
            )
            MockJudge.return_value.judge.return_value = publish_verdict

            orch = OrchestratorV2(deps)
            result = await orch.run(ConsultRequest(
                query="Transferencia datos bancarios EEUU",
                depth="deep",
            ))

        assert result.depth_used == "deep"
        assert result.iterations == 1
        assert result.judge_verdict is not None
        assert result.judge_verdict["verdict"] == "publish"
        assert result.judge_verdict["scores"]["factual_support"] == 0.9

    async def test_jurisdictions_propagated_to_planner_output(self) -> None:
        """EU, ES, US jurisdictions from plan must appear in response planner_output."""
        deps = _make_deps()

        with (
            patch("lex_agents_agents.core.orchestrator_v2.QueryRouter"),
            patch("lex_agents_agents.core.orchestrator_v2.LegalPlanner") as MockPlanner,
            patch("lex_agents_agents.core.orchestrator_v2.LegalJudge"),
            patch("lex_agents_agents.core.orchestrator_v2.CrossJurisdictionCoordinator") as MockCoord,
        ):
            plan = _make_cross_jurisdiction_plan()
            MockPlanner.return_value.plan.return_value = plan

            synth_resp = _make_agent_response("t3", "Respuesta")
            MockCoord.return_value.run_parallel = AsyncMock(return_value=[synth_resp, synth_resp])
            MockCoord.return_value.synthesize.return_value = synth_resp

            orch = OrchestratorV2(deps)
            result = await orch.run(ConsultRequest(query="consulta", depth="standard"))

        assert "EU" in result.planner_output["jurisdictions"]
        assert "US" in result.planner_output["jurisdictions"]
