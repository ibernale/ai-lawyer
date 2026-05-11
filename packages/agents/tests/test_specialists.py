"""Tests for specialist agents — smoke tests per branch, penal sets legal caveat."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from lex_agents_agents.base_agent import AgentResponse
from lex_agents_agents.routing.branch_classifier import get_specialist_class
from lex_agents_agents.shared.definition_of_done import BranchTask

_ALL_BRANCHES = [
    "regulatorio_bancario_ue_es",
    "datos_personales_rgpd",
    "laboral",
    "mercantil_societario",
    "penal_economico",
    "administrativo",
]

_QUERY = "Consulta de prueba para validar el especialista."


def _make_client() -> MagicMock:
    return MagicMock()


def _make_assembled() -> MagicMock:
    assembled = MagicMock()
    assembled.context_text = "Contexto normativo de prueba."
    assembled.citation_mapping = []
    return assembled


def _mock_invoke_response(trace_id: str) -> AgentResponse:
    from lex_agents_agents.base_agent import AgentMetadata
    return AgentResponse(
        trace_id=trace_id,
        answer_text="## Respuesta\nAnálisis normativo.",
        citations=[],
        verification=None,
        metadata=AgentMetadata(
            trace_id=trace_id,
            prompt_name="test",
            prompt_version=1,
            prompt_hash="abc123",
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=200,
            latency_ms=400.0,
            cost_estimate_usd=0.02,
        ),
        query_rewritten=_QUERY,
    )


def _make_specialist(branch_id: str, client: MagicMock):
    cls = get_specialist_class(branch_id)
    with patch("lex_agents_agents.core.specialist_base.load_prompt") as mock_load:
        cfg = MagicMock()
        cfg.version = 1
        cfg.content_hash = "feedcafe1234"
        cfg.model = "claude-opus-4-7"
        cfg.max_tokens = 4096
        cfg.body = f"System prompt for {branch_id}."
        cfg.name = f"especialistas/{branch_id}"
        mock_load.return_value = cfg
        return cls(client)


@pytest.mark.parametrize("branch_id", _ALL_BRANCHES)
@pytest.mark.asyncio
async def test_specialist_smoke(branch_id: str) -> None:
    """Each specialist returns an AgentResponse with required fields."""
    client = _make_client()
    specialist = _make_specialist(branch_id, client)
    assembled = _make_assembled()

    base_resp = _mock_invoke_response("trace-smoke")

    with patch.object(specialist, "_invoke", return_value=base_resp):
        result = await specialist.run_async(_QUERY, assembled, "trace-smoke")

    assert isinstance(result, AgentResponse)
    assert result.trace_id == "trace-smoke"
    assert result.answer_text


@pytest.mark.asyncio
async def test_penal_adds_legal_caveat() -> None:
    """PenalEconomicoAgent must append the AVISO LEGAL footer to the answer."""
    client = _make_client()
    specialist = _make_specialist("penal_economico", client)
    assembled = _make_assembled()

    base_resp = _mock_invoke_response("trace-penal")

    with patch.object(specialist, "_invoke", return_value=base_resp):
        result = await specialist.run_async(_QUERY, assembled, "trace-penal")

    assert "AVISO LEGAL" in result.answer_text
    assert "estrategia de defensa" in result.answer_text.lower() or "letrado" in result.answer_text.lower()


@pytest.mark.asyncio
async def test_penal_extra_caveat_passed_to_invoke() -> None:
    """PenalEconomicoAgent passes _PENAL_CAVEAT as extra_caveat to _invoke."""
    client = _make_client()
    specialist = _make_specialist("penal_economico", client)
    assembled = _make_assembled()

    captured: dict = {}
    base_resp = _mock_invoke_response("trace-penal2")

    def capture_invoke(query, asm, trace_id, span_name=None, extra_caveat=None):
        captured["extra_caveat"] = extra_caveat
        return base_resp

    with patch.object(specialist, "_invoke", side_effect=capture_invoke):
        await specialist.run_async(_QUERY, assembled, "trace-penal2")

    assert captured.get("extra_caveat") is not None
    assert "RECORDATORIO" in captured["extra_caveat"]


@pytest.mark.asyncio
async def test_sub_task_query_overrides_query() -> None:
    """When sub_task is provided, the specialist uses sub_task.query instead of the main query."""
    client = _make_client()
    specialist = _make_specialist("laboral", client)
    assembled = _make_assembled()

    sub_task = BranchTask(
        id="T1", branch="laboral", priority=1, weight=1.0,
        query="Consulta específica del subtask",
        expected_artifacts=[],
    )
    base_resp = _mock_invoke_response("trace-subtask")
    captured: dict = {}

    def capture_invoke(query, asm, trace_id, span_name=None, extra_caveat=None):
        captured["query"] = query
        return base_resp

    with patch.object(specialist, "_invoke", side_effect=capture_invoke):
        await specialist.run_async(_QUERY, assembled, "trace-subtask", sub_task=sub_task)

    assert captured["query"] == "Consulta específica del subtask"


class TestBranchRegistry:
    def test_all_known_branches_resolve(self) -> None:
        for branch_id in _ALL_BRANCHES:
            cls = get_specialist_class(branch_id)
            assert cls is not None
            assert cls.branch_id == branch_id

    def test_unknown_branch_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown branch"):
            get_specialist_class("rama_inexistente")
