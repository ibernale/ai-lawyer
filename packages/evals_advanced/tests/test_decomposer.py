"""Tests for LDPDecomposer — tool-use path, fallback, normalization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lex_agents_evals_advanced.lemaj.decomposer import LDPDecomposer, _heuristic_decompose
from lex_agents_evals_advanced.types import LegalDataPoint


def _make_client() -> MagicMock:
    return MagicMock()


def _tool_use_response(ldps: list[dict]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"ldps": ldps}
    resp = MagicMock()
    resp.content = [block]
    return resp


def _no_tool_response() -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = "Here is the analysis."
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestDecomposer:
    def test_happy_path_returns_ldps(self):
        client = _make_client()
        client.messages_create.return_value = _tool_use_response([
            {
                "claim_text": "El CRR exige un ratio mínimo del 8%.",
                "claim_type": "factual",
                "supporting_refs": ["REF:1"],
                "jurisdiction_scope": "EU",
                "context": "Según el artículo 92 CRR...",
            },
            {
                "claim_text": "Las entidades deben notificar en 15 días hábiles.",
                "claim_type": "procedural",
                "supporting_refs": [],
                "jurisdiction_scope": "ES",
                "context": "La normativa española establece...",
            },
        ])
        decomposer = LDPDecomposer(client)
        ldps = decomposer.decompose("test answer", [], "CASE-001")

        assert len(ldps) == 2
        assert ldps[0].ldp_id == "CASE-001-LDP-1"
        assert ldps[0].claim_type == "factual"
        assert ldps[0].jurisdiction_scope == "EU"
        assert ldps[1].ldp_id == "CASE-001-LDP-2"

    def test_claim_type_normalization(self):
        client = _make_client()
        client.messages_create.return_value = _tool_use_response([
            {
                "claim_text": "Some claim.",
                "claim_type": "FACTUAL",  # uppercase — should be normalized
                "supporting_refs": [],
                "jurisdiction_scope": "global",
                "context": "",
            },
        ])
        decomposer = LDPDecomposer(client)
        ldps = decomposer.decompose("answer", [], "CASE-002")
        assert ldps[0].claim_type == "factual"

    def test_jurisdiction_normalization(self):
        client = _make_client()
        client.messages_create.return_value = _tool_use_response([
            {
                "claim_text": "Some claim.",
                "claim_type": "interpretive",
                "supporting_refs": [],
                "jurisdiction_scope": "UNKNOWN_SCOPE",  # invalid
                "context": "",
            },
        ])
        decomposer = LDPDecomposer(client)
        ldps = decomposer.decompose("answer", [], "CASE-003")
        assert ldps[0].jurisdiction_scope == "unknown"

    def test_fallback_on_api_error(self):
        client = _make_client()
        client.messages_create.side_effect = RuntimeError("API down")
        decomposer = LDPDecomposer(client)
        # Sentences must be > 30 chars to pass the heuristic length filter
        ldps = decomposer.decompose(
            "El CRR exige un ratio mínimo de capital del ocho por ciento. "
            "La directiva MIFID II regula los mercados de instrumentos financieros.",
            [], "CASE-004",
        )
        # Fallback produces at least 1 LDP from heuristic sentence split
        assert len(ldps) >= 1
        assert all(isinstance(lv, LegalDataPoint) for lv in ldps)

    def test_fallback_on_no_tool_use(self):
        client = _make_client()
        client.messages_create.return_value = _no_tool_response()
        decomposer = LDPDecomposer(client)
        ldps = decomposer.decompose(
            "El capital mínimo regulatorio exige cumplir con el artículo 92 CRR. "
            "Las entidades deben notificar al supervisor en un plazo de quince días hábiles.",
            [], "CASE-005",
        )
        assert len(ldps) >= 1

    def test_empty_answer_returns_empty(self):
        client = _make_client()
        decomposer = LDPDecomposer(client)
        ldps = decomposer.decompose("", [], "CASE-006")
        assert ldps == []

    def test_heuristic_decompose_direct(self):
        ldps = _heuristic_decompose(
            "El reglamento CRR establece requisitos mínimos de capital para las entidades bancarias. "
            "La directiva MIFID II regula los servicios de inversión en toda la Unión Europea.",
            "CASE-007",
        )
        assert len(ldps) >= 1
        assert all(lv.ldp_id.startswith("CASE-007") for lv in ldps)

    def test_supporting_refs_extracted_from_claim(self):
        client = _make_client()
        client.messages_create.return_value = _tool_use_response([
            {
                "claim_text": "Según [REF:2] y [REF:5] el ratio mínimo es del ocho por ciento.",
                "claim_type": "factual",
                "supporting_refs": [],  # empty — should be enriched from claim_text
                "jurisdiction_scope": "EU",
                "context": "Context with [REF:2].",
            },
        ])
        decomposer = LDPDecomposer(client)
        ldps = decomposer.decompose("answer", [], "CASE-008")
        # supporting_refs may include brackets: "[REF:2]" or bare "REF:2"
        refs_joined = " ".join(ldps[0].supporting_refs)
        assert "REF:2" in refs_joined
        assert "REF:5" in refs_joined
