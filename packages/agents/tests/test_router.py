"""Tests for QueryRouter — routing decisions via mocked Anthropic tool_use."""

from __future__ import annotations

from unittest.mock import MagicMock

from lex_agents_agents.router import QueryRouter


def _mock_client(input_data: dict | None = None, no_tool_use: bool = False) -> MagicMock:
    """Build a mock AnthropicClientWrapper that returns a tool_use block.

    v2 prompt format: ``branches`` (array), ``depth``, ``rationale``.
    """
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
            "branches": ["regulatorio_bancario_ue_es"],
            "depth": "standard",
            "rationale": "Banking regulation query.",
        }
        resp.content = [tool_block]

    client.messages_create.return_value = resp
    return client


class TestRouterBancarioEU:
    def test_routes_to_bancario(self) -> None:
        client = _mock_client({
            "branches": ["regulatorio_bancario_ue_es"],
            "depth": "standard",
            "rationale": "CRR capital requirements.",
        })
        router = QueryRouter(client)
        decision = router.route("¿Cuáles son los requisitos CET1 bajo el CRR?")
        assert decision.branch == "regulatorio_bancario_ue_es"

    def test_routes_deep_for_complex_query(self) -> None:
        client = _mock_client({
            "branches": ["regulatorio_bancario_ue_es"],
            "depth": "deep",
            "rationale": "Multi-norm analysis.",
        })
        router = QueryRouter(client)
        decision = router.route("Análisis complejo multi-norma")
        assert decision.depth == "deep"


class TestRouterDatosPersonales:
    """Regression tests for false-negative bug: datos_personales routed to fuera_de_alcance."""

    def test_proteccion_datos_espana_routes_to_rgpd(self) -> None:
        """¿qué regulación de protección de datos aplica en españa? must NOT be fuera_de_alcance."""
        client = _mock_client({
            "branches": ["datos_personales_rgpd"],
            "depth": "shallow",
            "rationale": "RGPD/LOPDGDD scope query.",
        })
        router = QueryRouter(client)
        decision = router.route("¿qué regulación de protección de datos aplica en españa?")
        assert decision.branch == "datos_personales_rgpd"
        assert decision.branch != "fuera_de_alcance"

    def test_rgpd_obligations_routes_to_rgpd(self) -> None:
        client = _mock_client({
            "branches": ["datos_personales_rgpd"],
            "depth": "standard",
            "rationale": "RGPD controller obligations.",
        })
        router = QueryRouter(client)
        decision = router.route("¿Qué obligaciones impone el RGPD a los responsables del tratamiento?")
        assert decision.branch == "datos_personales_rgpd"

    def test_multi_branch_takes_primary(self) -> None:
        """When branches returns [laboral, datos_personales_rgpd], primary branch is laboral."""
        client = _mock_client({
            "branches": ["laboral", "datos_personales_rgpd"],
            "depth": "standard",
            "rationale": "Employee data breach — dual scope.",
        })
        router = QueryRouter(client)
        decision = router.route("Despido de empleado que accedió a datos de clientes sin autorización")
        assert decision.branch == "laboral"


class TestRouterFueraDeAlcance:
    def test_routes_out_of_scope(self) -> None:
        client = _mock_client({
            "branches": ["fuera_de_alcance"],
            "depth": "shallow",
            "rationale": "Tax law — not in scope.",
        })
        router = QueryRouter(client)
        decision = router.route("¿Cuándo prescribe el IVA en España?")
        assert decision.branch == "fuera_de_alcance"

    def test_unknown_branch_value_defaults_to_fuera_de_alcance(self) -> None:
        """Unknown branch string silently degrades to fuera_de_alcance."""
        client = _mock_client({
            "branches": ["unknown_branch_xyz"],
            "depth": "shallow",
            "rationale": "...",
        })
        router = QueryRouter(client)
        decision = router.route("any query")
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
