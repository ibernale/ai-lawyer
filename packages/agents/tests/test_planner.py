"""Tests for LegalPlanner — schema validation, single/multi-branch planning."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lex_agents_agents.core.planner import LegalPlanner, _DEFAULT_OUTPUT
from lex_agents_agents.shared.definition_of_done import BranchTask, DefinitionOfDone, PlannerOutput


def _make_client() -> MagicMock:
    client = MagicMock()
    client.messages_create.return_value = MagicMock(
        usage=MagicMock(input_tokens=100, output_tokens=50),
        content=[],
    )
    return client


def _make_tool_response(raw: dict) -> MagicMock:
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = raw
    resp = MagicMock()
    resp.usage = MagicMock(input_tokens=200, output_tokens=100)
    resp.content = [tool_block]
    return resp


def _make_planner(client: MagicMock) -> LegalPlanner:
    with patch("lex_agents_agents.core.planner.load_prompt") as mock_load:
        cfg = MagicMock()
        cfg.version = 1
        cfg.content_hash = "abc123def456"
        cfg.model = "claude-opus-4-7"
        cfg.max_tokens = 4096
        cfg.body = "You are a planner."
        mock_load.return_value = cfg
        return LegalPlanner(client)


class TestPlannerSchema:
    def test_single_branch_output(self) -> None:
        client = _make_client()
        planner = _make_planner(client)

        raw = {
            "branches": [{"name": "regulatorio_bancario_ue_es", "priority": 1, "weight": 1.0}],
            "jurisdictions": ["EU", "ES"],
            "output_type": "dictamen",
            "depth": "standard",
            "sub_tasks": [
                {
                    "id": "T1",
                    "branch": "regulatorio_bancario_ue_es",
                    "priority": 1,
                    "weight": 1.0,
                    "query": "ratio CET1",
                    "expected_artifacts": ["ratio_capital"],
                }
            ],
            "definition_of_done": {
                "must_cover_concepts": ["CET1", "CRR"],
                "must_consider_jurisdictions": ["EU"],
                "must_address_caveats": ["regulación en vigor"],
                "out_of_scope": ["penales"],
            },
        }
        client.messages_create.return_value = _make_tool_response(raw)

        result = planner.plan("¿CET1 mínimo bajo CRR?")

        assert isinstance(result, PlannerOutput)
        assert len(result.branches) == 1
        assert result.branches[0]["name"] == "regulatorio_bancario_ue_es"
        assert result.jurisdictions == ["EU", "ES"]
        assert result.output_type == "dictamen"
        assert result.depth == "standard"
        assert len(result.sub_tasks) == 1
        assert isinstance(result.sub_tasks[0], BranchTask)
        assert result.sub_tasks[0].branch == "regulatorio_bancario_ue_es"
        assert isinstance(result.definition_of_done, DefinitionOfDone)
        assert "CET1" in result.definition_of_done.must_cover_concepts

    def test_multi_branch_output(self) -> None:
        client = _make_client()
        planner = _make_planner(client)

        raw = {
            "branches": [
                {"name": "regulatorio_bancario_ue_es", "priority": 1, "weight": 0.6},
                {"name": "datos_personales_rgpd", "priority": 2, "weight": 0.4},
            ],
            "jurisdictions": ["EU", "ES", "US"],
            "output_type": "dictamen",
            "depth": "deep",
            "sub_tasks": [
                {
                    "id": "T1",
                    "branch": "regulatorio_bancario_ue_es",
                    "priority": 1,
                    "weight": 0.6,
                    "query": "transferencia datos EEUU",
                    "expected_artifacts": ["prudential_analysis"],
                },
                {
                    "id": "T2",
                    "branch": "datos_personales_rgpd",
                    "priority": 2,
                    "weight": 0.4,
                    "query": "protección datos EEUU",
                    "expected_artifacts": ["rgpd_analysis"],
                },
            ],
            "definition_of_done": {
                "must_cover_concepts": ["transferencia internacional", "RGPD"],
                "must_consider_jurisdictions": ["EU", "US"],
                "must_address_caveats": ["adecuación US no vigente"],
                "out_of_scope": [],
            },
        }
        client.messages_create.return_value = _make_tool_response(raw)

        result = planner.plan("Transferencia datos a filial en EEUU")

        assert len(result.branches) == 2
        assert len(result.sub_tasks) == 2
        assert result.sub_tasks[0].branch == "regulatorio_bancario_ue_es"
        assert result.sub_tasks[1].branch == "datos_personales_rgpd"
        assert result.depth == "deep"

    def test_depth_hint_overrides_llm(self) -> None:
        client = _make_client()
        planner = _make_planner(client)

        raw = {
            "branches": [{"name": "laboral", "priority": 1, "weight": 1.0}],
            "jurisdictions": ["ES"],
            "output_type": "dictamen",
            "depth": "standard",  # LLM says standard
            "sub_tasks": [
                {
                    "id": "T1",
                    "branch": "laboral",
                    "priority": 1,
                    "weight": 1.0,
                    "query": "ERE",
                    "expected_artifacts": [],
                }
            ],
            "definition_of_done": {
                "must_cover_concepts": [],
                "must_consider_jurisdictions": [],
                "must_address_caveats": [],
                "out_of_scope": [],
            },
        }
        client.messages_create.return_value = _make_tool_response(raw)

        result = planner.plan("ERE en empresa de 200 trabajadores", depth_hint="deep")

        # depth_hint must override LLM's "standard"
        assert result.depth == "deep"

    def test_api_error_returns_default(self) -> None:
        client = _make_client()
        planner = _make_planner(client)
        client.messages_create.side_effect = Exception("API down")

        result = planner.plan("cualquier consulta jurídica")

        assert result is _DEFAULT_OUTPUT or result.branches[0]["name"] == "fuera_de_alcance"

    def test_no_tool_use_returns_default(self) -> None:
        client = _make_client()
        planner = _make_planner(client)
        resp = MagicMock()
        resp.usage = MagicMock(input_tokens=50, output_tokens=20)
        resp.content = [MagicMock(type="text")]  # no tool_use block
        client.messages_create.return_value = resp

        result = planner.plan("consulta sin respuesta tool")

        assert result.branches[0]["name"] == "fuera_de_alcance"
