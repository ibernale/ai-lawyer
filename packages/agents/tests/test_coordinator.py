"""Tests for CrossJurisdictionCoordinator — parallel execution, synthesis, citation merging."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lex_agents_agents.base_agent import AgentMetadata, AgentResponse
from lex_agents_agents.core.coordinator import CrossJurisdictionCoordinator
from lex_agents_agents.shared.definition_of_done import BranchTask, PlannerOutput
from lex_agents_shared.types import CitationMapping


def _make_client() -> MagicMock:
    return MagicMock()


def _make_coordinator(client: MagicMock) -> CrossJurisdictionCoordinator:
    with patch("lex_agents_agents.core.coordinator.load_prompt") as mock_load:
        cfg = MagicMock()
        cfg.version = 2
        cfg.content_hash = "cafebabe1234"
        cfg.model = "claude-opus-4-7"
        cfg.max_tokens = 8192
        cfg.body = "Synthesis prompt v2."
        cfg.name = "sintesis"
        mock_load.return_value = cfg
        return CrossJurisdictionCoordinator(client)


def _make_agent_response(
    text: str = "Respuesta",
    citations: list[CitationMapping] | None = None,
    trace_id: str = "t1",
) -> AgentResponse:
    return AgentResponse(
        trace_id=trace_id,
        answer_text=text,
        citations=citations or [],
        verification=None,
        metadata=AgentMetadata(
            trace_id=trace_id,
            prompt_name="test_branch",
            prompt_version=1,
            prompt_hash="abc",
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=200,
            latency_ms=500.0,
            cost_estimate_usd=0.02,
        ),
        query_rewritten="consulta",
    )


def _make_planner_output(branches: list[str], weights: list[float] | None = None) -> PlannerOutput:
    weights = weights or [1.0 / len(branches)] * len(branches)
    from lex_agents_agents.shared.definition_of_done import DefinitionOfDone
    return PlannerOutput(
        branches=[{"name": b, "priority": i + 1, "weight": w} for i, (b, w) in enumerate(zip(branches, weights))],
        jurisdictions=["EU", "ES"],
        output_type="dictamen",
        depth="deep",
        sub_tasks=[
            BranchTask(id=f"T{i+1}", branch=b, priority=i + 1, weight=w, query="consulta", expected_artifacts=[])
            for i, (b, w) in enumerate(zip(branches, weights))
        ],
        definition_of_done=DefinitionOfDone(),
    )


@pytest.mark.asyncio
class TestRunParallel:
    async def test_parallel_execution_order(self) -> None:
        client = _make_client()
        coord = _make_coordinator(client)

        branches = ["regulatorio_bancario_ue_es", "datos_personales_rgpd"]
        tasks = [
            BranchTask(id="T1", branch="regulatorio_bancario_ue_es", priority=1, weight=0.6, query="banca", expected_artifacts=[]),
            BranchTask(id="T2", branch="datos_personales_rgpd", priority=2, weight=0.4, query="rgpd", expected_artifacts=[]),
        ]

        resp1 = _make_agent_response("Análisis bancario")
        resp2 = _make_agent_response("Análisis RGPD")

        assembled = MagicMock()
        assembled.context_text = "context"
        assembled.citation_mapping = []

        mock_specialist_cls1 = MagicMock()
        mock_specialist1 = MagicMock()
        mock_specialist1.run_async = AsyncMock(return_value=resp1)
        mock_specialist_cls1.return_value = mock_specialist1

        mock_specialist_cls2 = MagicMock()
        mock_specialist2 = MagicMock()
        mock_specialist2.run_async = AsyncMock(return_value=resp2)
        mock_specialist_cls2.return_value = mock_specialist2

        def get_cls(branch_id: str):
            return mock_specialist_cls1 if branch_id == "regulatorio_bancario_ue_es" else mock_specialist_cls2

        with patch("lex_agents_agents.core.coordinator.get_specialist_class", side_effect=get_cls):
            results = await coord.run_parallel(tasks, assembled, "trace-x")

        assert len(results) == 2
        texts = [r.answer_text for r in results]
        assert "Análisis bancario" in texts
        assert "Análisis RGPD" in texts

    async def test_single_task_passthrough_in_synthesize(self) -> None:
        client = _make_client()
        coord = _make_coordinator(client)

        single_resp = _make_agent_response("Solo bancario")
        plan = _make_planner_output(["regulatorio_bancario_ue_es"])

        result = coord.synthesize([single_resp], plan, "trace-y")

        assert result is single_resp
        client.messages_create.assert_not_called()


class TestSynthesize:
    def test_multi_branch_llm_synthesis(self) -> None:
        client = _make_client()
        coord = _make_coordinator(client)

        resp_msg = MagicMock()
        resp_msg.content = [MagicMock(text="Dictamen integrado EU > ES.")]
        resp_msg.usage = MagicMock(input_tokens=500, output_tokens=300)
        client.messages_create.return_value = resp_msg

        responses = [
            _make_agent_response("Bancario: ratio CET1 mínimo 4.5%"),
            _make_agent_response("RGPD: transferencia requiere SCCs"),
        ]
        plan = _make_planner_output(["regulatorio_bancario_ue_es", "datos_personales_rgpd"], [0.6, 0.4])

        result = coord.synthesize(responses, plan, "trace-z")

        assert result.answer_text == "Dictamen integrado EU > ES."
        client.messages_create.assert_called_once()
        call_args = client.messages_create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "regulatorio_bancario_ue_es" in user_content
        assert "datos_personales_rgpd" in user_content

    def test_synthesis_fallback_on_api_error(self) -> None:
        client = _make_client()
        coord = _make_coordinator(client)
        client.messages_create.side_effect = Exception("API error")

        responses = [
            _make_agent_response("Bancario"),
            _make_agent_response("RGPD"),
        ]
        plan = _make_planner_output(["regulatorio_bancario_ue_es", "datos_personales_rgpd"])

        result = coord.synthesize(responses, plan, "trace-fallback")

        assert "Bancario" in result.answer_text
        assert "RGPD" in result.answer_text
        assert "---" in result.answer_text


class TestMergeCitations:
    def test_sequential_renumbering(self) -> None:
        client = _make_client()
        coord = _make_coordinator(client)

        cit1 = CitationMapping(index=1, chunk_id="c1", source_id="src1", hierarchy_path="A>B", fragment_text="texto 1")
        cit2 = CitationMapping(index=1, chunk_id="c2", source_id="src2", hierarchy_path="C>D", fragment_text="texto 2")
        cit3 = CitationMapping(index=2, chunk_id="c3", source_id="src3", hierarchy_path="E>F", fragment_text="texto 3")

        resp1 = _make_agent_response(citations=[cit1, cit2])
        resp2 = _make_agent_response(citations=[cit3])

        merged = coord._merge_citations([resp1, resp2])

        assert len(merged) == 3
        assert merged[0].index == 1
        assert merged[1].index == 2
        assert merged[2].index == 3

    def test_deduplication_by_source_chunk(self) -> None:
        client = _make_client()
        coord = _make_coordinator(client)

        cit = CitationMapping(index=1, chunk_id="c1", source_id="src1", hierarchy_path="A", fragment_text="texto")
        cit_dup = CitationMapping(index=1, chunk_id="c1", source_id="src1", hierarchy_path="A", fragment_text="texto")

        resp1 = _make_agent_response(citations=[cit])
        resp2 = _make_agent_response(citations=[cit_dup])

        merged = coord._merge_citations([resp1, resp2])

        assert len(merged) == 1
