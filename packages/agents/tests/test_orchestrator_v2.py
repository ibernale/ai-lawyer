"""Tests for OrchestratorV2 — shallow/standard/deep paths, depth override, backwards compat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lex_agents_agents.base_agent import AgentMetadata, AgentResponse, RoutingDecision
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
    rewritten.expanded_query = "expanded query"
    query_rewriter = MagicMock()
    query_rewriter.rewrite.return_value = rewritten

    assembled = MagicMock()
    assembled.context_text = "Context"
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


def _make_agent_response(trace_id: str = "t1", text: str = "Respuesta legal.") -> AgentResponse:
    return AgentResponse(
        trace_id=trace_id,
        answer_text=text,
        citations=[],
        verification=None,
        metadata=AgentMetadata(
            trace_id=trace_id,
            prompt_name="especialistas/regulatorio_bancario_ue_es",
            prompt_version=1,
            prompt_hash="abc123",
            model="claude-opus-4-7",
            input_tokens=200,
            output_tokens=400,
            latency_ms=600.0,
            cost_estimate_usd=0.033,
        ),
        query_rewritten="expanded query",
    )


def _make_plan(branches: list[str], depth: str = "standard") -> PlannerOutput:
    return PlannerOutput(
        branches=[{"name": b, "priority": i + 1, "weight": 1.0 / len(branches)} for i, b in enumerate(branches)],
        jurisdictions=["EU", "ES"],
        output_type="dictamen",
        depth=depth,
        sub_tasks=[
            BranchTask(id=f"T{i+1}", branch=b, priority=i + 1, weight=1.0 / len(branches), query="q", expected_artifacts=[])
            for i, b in enumerate(branches)
        ],
        definition_of_done=DefinitionOfDone(must_cover_concepts=["CET1"]),
    )


def _make_orchestrator(deps: OrchestratorDeps) -> OrchestratorV2:
    with (
        patch("lex_agents_agents.core.orchestrator_v2.QueryRouter"),
        patch("lex_agents_agents.core.orchestrator_v2.LegalPlanner"),
        patch("lex_agents_agents.core.orchestrator_v2.LegalJudge"),
        patch("lex_agents_agents.core.orchestrator_v2.CrossJurisdictionCoordinator"),
    ):
        return OrchestratorV2(deps)


@pytest.mark.asyncio
class TestShallowPath:
    async def test_shallow_single_specialist(self) -> None:
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        agent_resp = _make_agent_response("trace-shallow")
        decision = RoutingDecision(branch="regulatorio_bancario_ue_es", jurisdictions=["EU"], output_type="dictamen", depth="shallow")
        orch._router.route.return_value = decision

        mock_cls = MagicMock()
        mock_specialist = MagicMock()
        mock_specialist.run_async = AsyncMock(return_value=agent_resp)
        mock_cls.return_value = mock_specialist

        with patch("lex_agents_agents.core.orchestrator_v2.get_specialist_class", return_value=mock_cls):
            result = await orch.run(ConsultRequest(query="CET1 mínimo", depth="shallow"))

        assert isinstance(result, ConsultResponse)
        assert result.depth_used == "shallow"
        assert result.iterations == 0
        assert result.planner_output is None
        assert result.answer == agent_resp.answer_text

    async def test_shallow_out_of_scope(self) -> None:
        deps = _make_deps()
        orch = _make_orchestrator(deps)
        orch._router.route.return_value = RoutingDecision(
            branch="fuera_de_alcance", jurisdictions=[], output_type="dictamen", depth="shallow"
        )

        result = await orch.run(ConsultRequest(query="Consulta fuera de alcance", depth="shallow"))

        assert result.routing["branch"] == "fuera_de_alcance"
        assert result.citations == []
        assert result.depth_used == "shallow"
        deps.retriever.search.assert_not_called()


@pytest.mark.asyncio
class TestStandardPath:
    async def test_standard_single_branch(self) -> None:
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        plan = _make_plan(["regulatorio_bancario_ue_es"], depth="standard")
        orch._planner.plan.return_value = plan

        agent_resp = _make_agent_response("trace-std")
        mock_cls = MagicMock()
        mock_specialist = MagicMock()
        mock_specialist.run_async = AsyncMock(return_value=agent_resp)
        mock_cls.return_value = mock_specialist

        with patch("lex_agents_agents.core.orchestrator_v2.get_specialist_class", return_value=mock_cls):
            result = await orch.run(ConsultRequest(query="CET1 mínimo", depth="standard"))

        assert result.depth_used == "standard"
        assert result.planner_output is not None
        assert result.planner_output["branches"][0]["name"] == "regulatorio_bancario_ue_es"

    async def test_standard_multi_branch_uses_coordinator(self) -> None:
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        plan = _make_plan(["regulatorio_bancario_ue_es", "datos_personales_rgpd"])
        orch._planner.plan.return_value = plan

        synth_resp = _make_agent_response("trace-multi", text="Dictamen integrado")
        orch._coordinator.run_parallel = AsyncMock(return_value=[_make_agent_response(), _make_agent_response()])
        orch._coordinator.synthesize.return_value = synth_resp

        result = await orch.run(ConsultRequest(query="Transferencia datos EEUU", depth="standard"))

        assert result.depth_used == "standard"
        orch._coordinator.run_parallel.assert_awaited_once()
        orch._coordinator.synthesize.assert_called_once()

    async def test_standard_out_of_scope(self) -> None:
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        out_of_scope_plan = _make_plan(["fuera_de_alcance"])
        out_of_scope_plan.sub_tasks = []  # No tasks → out of scope
        orch._planner.plan.return_value = out_of_scope_plan

        result = await orch.run(ConsultRequest(query="Algo irrelevante", depth="standard"))

        assert result.routing["branch"] == "fuera_de_alcance"


@pytest.mark.asyncio
class TestDeepPath:
    async def test_deep_publish_on_first_iteration(self) -> None:
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        plan = _make_plan(["regulatorio_bancario_ue_es"], depth="deep")
        orch._planner.plan.return_value = plan

        agent_resp = _make_agent_response("trace-deep")
        mock_cls = MagicMock()
        mock_specialist = MagicMock()
        mock_specialist.run_async = AsyncMock(return_value=agent_resp)
        mock_cls.return_value = mock_specialist

        publish_verdict = JudgeVerdict(
            verdict="publish",
            scores={"factual_support": 0.9, "completeness": 0.9, "jurisdictional_correctness": 0.9, "caveat_appropriateness": 0.9, "internal_consistency": 0.9},
            gaps=[],
            iteration_brief="Aprobado.",
            iteration=1,
        )
        orch._judge.judge.return_value = publish_verdict

        with patch("lex_agents_agents.core.orchestrator_v2.get_specialist_class", return_value=mock_cls):
            result = await orch.run(ConsultRequest(query="CET1 mínimo", depth="deep"))

        assert result.depth_used == "deep"
        assert result.iterations == 1
        assert result.judge_verdict is not None
        assert result.judge_verdict["verdict"] == "publish"
        orch._judge.judge.assert_called_once()

    async def test_deep_revise_then_publish(self) -> None:
        """Two iterations: revise on iter 1, publish on iter 2."""
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        plan = _make_plan(["regulatorio_bancario_ue_es"], depth="deep")
        orch._planner.plan.return_value = plan

        agent_resp = _make_agent_response("trace-deep2")
        mock_cls = MagicMock()
        mock_specialist = MagicMock()
        mock_specialist.run_async = AsyncMock(return_value=agent_resp)
        mock_cls.return_value = mock_specialist

        revise_verdict = JudgeVerdict(
            verdict="revise", scores={}, gaps=["gap1"], iteration_brief="Revisar X.", iteration=1
        )
        publish_verdict = JudgeVerdict(
            verdict="publish", scores={}, gaps=[], iteration_brief="Ok.", iteration=2
        )
        orch._judge.judge.side_effect = [revise_verdict, publish_verdict]

        with patch("lex_agents_agents.core.orchestrator_v2.get_specialist_class", return_value=mock_cls):
            result = await orch.run(ConsultRequest(query="CET1 con revisión", depth="deep"))

        assert result.depth_used == "deep"
        assert result.iterations == 2
        assert orch._judge.judge.call_count == 2

    async def test_deep_depth_defaults_to_standard_when_none(self) -> None:
        """depth=None defaults to 'standard', not 'deep'."""
        deps = _make_deps()
        orch = _make_orchestrator(deps)

        plan = _make_plan(["regulatorio_bancario_ue_es"])
        orch._planner.plan.return_value = plan

        agent_resp = _make_agent_response("trace-default")
        mock_cls = MagicMock()
        mock_specialist = MagicMock()
        mock_specialist.run_async = AsyncMock(return_value=agent_resp)
        mock_cls.return_value = mock_specialist

        with patch("lex_agents_agents.core.orchestrator_v2.get_specialist_class", return_value=mock_cls):
            result = await orch.run(ConsultRequest(query="consulta sin depth"))

        assert result.depth_used == "standard"


class TestBackwardsCompat:
    def test_orchestrator_shim_re_exports(self) -> None:
        """Root orchestrator.py shim re-exports from orchestrator_v2."""
        from lex_agents_agents import orchestrator as shim
        from lex_agents_agents.core.orchestrator_v2 import OrchestratorV2

        assert shim.Orchestrator is OrchestratorV2

    def test_consult_request_has_depth_field(self) -> None:
        req = ConsultRequest(query="test consulta")
        assert req.depth is None

        req_deep = ConsultRequest(query="test consulta", depth="deep")
        assert req_deep.depth == "deep"

    def test_consult_response_has_pmj_fields(self) -> None:
        resp = ConsultResponse(
            trace_id="t",
            answer="a",
            citations=[],
            verification=None,
            query_rewritten="q",
            routing={},
            metadata={},
        )
        assert resp.depth_used == "standard"
        assert resp.iterations == 0
        assert resp.planner_output is None
        assert resp.judge_verdict is None
        assert resp.cost_breakdown_by_agent == {}
