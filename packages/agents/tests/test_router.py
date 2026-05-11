"""Tests for QueryRouter — routing decisions via mocked Anthropic tool_use."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lex_agents_agents.base_agent import RoutingDecision
from lex_agents_agents.router import QueryRouter


def _mock_client(input_data: dict | None = None, no_tool_use: bool = False) -> MagicMock:
    """Build a mock AnthropicClientWrapper that returns a tool_use block."""
    client = MagicMock()
    resp = MagicMock()
    resp.usage.input_tokens = 50
    resp.usage.output_tokens = 30

    if no_tool_use:
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I cannot route this."
        resp.content = [text_block]
    else:
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.input = input_data or {
            "branch": "regulatorio_bancario_ue_es",
            "jurisdictions": ["EU"],
            "output_type": "dictamen",
            "depth": "standard",
            "sub_queries": [],
        }
        resp.content = [tool_block]

    client.messages_create.return_value = resp
    return client


class TestRouterBancarioEU:
    def test_routes_to_bancario(self) -> None:
        client = _mock_client({
            "branch": "regulatorio_bancario_ue_es",
            "jurisdictions": ["EU"],
            "output_type": "dictamen",
            "depth": "standard",
            "sub_queries": [],
        })
        router = QueryRouter(client)
        decision = router.route("¿Cuáles son los requisitos CET1 bajo el CRR?")
        assert decision.branch == "regulatorio_bancario_ue_es"
        assert "EU" in decision.jurisdictions

    def test_routes_deep_for_complex_query(self) -> None:
        client = _mock_client({
            "branch": "regulatorio_bancario_ue_es",
            "jurisdictions": ["EU", "ES"],
            "output_type": "analisis_riesgo",
            "depth": "deep",
            "sub_queries": ["sub1", "sub2"],
        })
        router = QueryRouter(client)
        decision = router.route("Análisis complejo multi-norma")
        assert decision.depth == "deep"
        assert len(decision.sub_queries) == 2


class TestRouterFueraDeAlcance:
    def test_routes_out_of_scope(self) -> None:
        client = _mock_client({
            "branch": "fuera_de_alcance",
            "jurisdictions": [],
            "output_type": "dictamen",
            "depth": "shallow",
            "sub_queries": [],
        })
        router = QueryRouter(client)
        decision = router.route("¿Cuál es la indemnización por despido improcedente?")
        assert decision.branch == "fuera_de_alcance"


class TestInvalidToolOutputDefaultsFueraDeAlcance:
    def test_no_tool_use_block_defaults_to_out_of_scope(self) -> None:
        client = _mock_client(no_tool_use=True)
        router = QueryRouter(client)
        decision = router.route("any query")
        assert decision.branch == "fuera_de_alcance"

    def test_api_error_defaults_to_out_of_scope(self) -> None:
        client = MagicMock()
        client.messages_create.side_effect = RuntimeError("circuit open")
        router = QueryRouter(client)
        decision = router.route("any query")
        assert decision.branch == "fuera_de_alcance"
