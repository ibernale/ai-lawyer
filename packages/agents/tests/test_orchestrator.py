"""Tests for Orchestrator — full pipeline with mocked dependencies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lex_agents_agents.base_agent import AgentMetadata, AgentResponse, RoutingDecision
from lex_agents_agents.orchestrator import (
    ConsultRequest,
    ConsultResponse,
    Orchestrator,
    OrchestratorDeps,
)
from lex_agents_shared.types import CitationMapping, VerificationReport


def _make_deps(branch: str = "regulatorio_bancario_ue_es") -> OrchestratorDeps:
    retriever = MagicMock()
    retriever.search.return_value = []

    reranker = MagicMock()
    reranker.rerank.return_value = []

    query_rewriter = MagicMock()
    rewritten = MagicMock()
    rewritten.expanded_query = "expanded query"
    query_rewriter.rewrite.return_value = rewritten

    assembler = MagicMock()
    assembled = MagicMock()
    assembled.context_text = "Context text"
    assembled.citation_mapping = []
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


def _make_agent_response(trace_id: str) -> AgentResponse:
    return AgentResponse(
        trace_id=trace_id,
        answer_text="## 1. Cuestión planteada\nRatio CET1 [REF:1]",
        citations=[
            CitationMapping(
                index=1,
                chunk_id="chunk_001",
                source_id="32013R0575",
                hierarchy_path="CRR > Art. 92",
                fragment_text="artículo 92 ratio 4,5%",
            )
        ],
        verification=None,
        metadata=AgentMetadata(
            trace_id=trace_id,
            prompt_name="especialistas/regulatorio_bancario_ue_es",
            prompt_version=1,
            prompt_hash="abc123",
            model="claude-opus-4-7",
            input_tokens=500,
            output_tokens=800,
            latency_ms=1200.0,
            cost_estimate_usd=0.068,
        ),
        query_rewritten="expanded query",
    )


@pytest.mark.asyncio
class TestFullPipelineBancario:
    async def test_returns_consult_response(self) -> None:
        deps = _make_deps()
        orch = Orchestrator(deps)

        expected_resp = _make_agent_response("test-trace-1")

        with (
            patch.object(orch._router, "route", return_value=RoutingDecision(
                branch="regulatorio_bancario_ue_es",
                jurisdictions=["EU"],
                output_type="dictamen",
                depth="standard",
            )),
            patch.object(orch._specialist, "run", return_value=expected_resp),
        ):
            result = await orch.run(ConsultRequest(query="¿CET1 mínimo bajo CRR?"))

        assert isinstance(result, ConsultResponse)
        assert result.answer == expected_resp.answer_text
        assert len(result.citations) == 1
        assert result.routing["branch"] == "regulatorio_bancario_ue_es"

    async def test_citations_populated(self) -> None:
        deps = _make_deps()
        orch = Orchestrator(deps)
        expected_resp = _make_agent_response("test-trace-2")

        with (
            patch.object(orch._router, "route", return_value=RoutingDecision(
                branch="regulatorio_bancario_ue_es",
                jurisdictions=["EU"],
                output_type="dictamen",
                depth="standard",
            )),
            patch.object(orch._specialist, "run", return_value=expected_resp),
        ):
            result = await orch.run(ConsultRequest(query="CRR requisitos"))

        assert result.citations[0].source_id == "32013R0575"


@pytest.mark.asyncio
class TestFueraDeAlcanceSkipsRag:
    async def test_out_of_scope_returns_no_citations(self) -> None:
        deps = _make_deps()
        orch = Orchestrator(deps)

        with patch.object(orch._router, "route", return_value=RoutingDecision(
            branch="fuera_de_alcance",
            jurisdictions=[],
            output_type="dictamen",
            depth="shallow",
        )):
            result = await orch.run(ConsultRequest(query="¿Indemnización laboral?"))

        assert result.citations == []
        assert result.verification is None
        assert result.routing["branch"] == "fuera_de_alcance"
        # RAG should not have been called
        deps.retriever.search.assert_not_called()
        deps.assembler.assemble.assert_not_called()
