"""Tests for MetaJudge arbitration — low_confidence, tool_use, fallbacks."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from lex_agents_evals_advanced.lemaj.meta_judge import MetaJudge
from lex_agents_evals_advanced.types import JudgeDimensions, LegalDataPoint, SingleJudgeVerdict


def _make_ldp() -> LegalDataPoint:
    return LegalDataPoint(
        ldp_id="CASE-001-LDP-1",
        claim_text="MIFID II aplica a todos los intermediarios.",
        claim_type="interpretive",
        supporting_refs=["REF:3"],
        jurisdiction_scope="EU",
        context="Según Directiva 2014/65/UE...",
    )


def _make_verdicts(
    overall_a: str, overall_b: str, overall_c: str
) -> list[SingleJudgeVerdict]:
    dims = JudgeDimensions(
        factual_support="partial",
        normative_accuracy="partial",
        jurisdictional_correctness="supported",
        completeness_partial="partial",
        caveat_appropriateness="supported",
    )
    return [
        SingleJudgeVerdict(judge_id="A", model="claude-opus-4-7-20250514", dimensions=dims, overall=overall_a, reasoning="A reasoning"),  # type: ignore[arg-type]
        SingleJudgeVerdict(judge_id="B", model="claude-opus-4-7-20250514", dimensions=dims, overall=overall_b, reasoning="B reasoning"),  # type: ignore[arg-type]
        SingleJudgeVerdict(judge_id="C", model="claude-haiku-4-5-20251001", dimensions=dims, overall=overall_c, reasoning="C reasoning"),  # type: ignore[arg-type]
    ]


def _tool_response(final_verdict: str, low_confidence: bool, reasoning: str) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = {
        "final_verdict": final_verdict,
        "low_confidence": low_confidence,
        "reasoning": reasoning,
    }
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestMetaJudge:
    def test_arbitrate_returns_final_verdict(self):
        client = MagicMock()
        client.messages_create.return_value = _tool_response("partial", False, "Judges A and B agree.")
        meta = MetaJudge(client)
        verdict, reasoning = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("supported", "partial", "partial"))
        )
        assert verdict == "partial"
        assert "Judges" in reasoning

    def test_low_confidence_returns_review_required(self):
        client = MagicMock()
        client.messages_create.return_value = _tool_response("partial", True, "Ambiguous normativa.")
        meta = MetaJudge(client)
        verdict, _ = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("supported", "unsupported", "partial"))
        )
        assert verdict == "review_required"

    def test_total_disagreement_review_required(self):
        client = MagicMock()
        client.messages_create.return_value = _tool_response("review_required", True, "No consensus possible.")
        meta = MetaJudge(client)
        verdict, reasoning = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("supported", "unsupported", "partial"))
        )
        assert verdict == "review_required"

    def test_api_error_returns_review_required(self):
        client = MagicMock()
        client.messages_create.side_effect = RuntimeError("connection error")
        meta = MetaJudge(client)
        verdict, reasoning = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("partial", "partial", "supported"))
        )
        assert verdict == "review_required"
        assert "error" in reasoning.lower()

    def test_no_tool_use_returns_review_required(self):
        client = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = "I cannot decide."
        resp = MagicMock()
        resp.content = [block]
        client.messages_create.return_value = resp
        meta = MetaJudge(client)
        verdict, _ = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("partial", "supported", "unsupported"))
        )
        assert verdict == "review_required"

    def test_supported_verdict_passes_through(self):
        client = MagicMock()
        client.messages_create.return_value = _tool_response("supported", False, "All consistent.")
        meta = MetaJudge(client)
        verdict, _ = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("supported", "supported", "partial"))
        )
        assert verdict == "supported"

    def test_unsupported_verdict_passes_through(self):
        client = MagicMock()
        client.messages_create.return_value = _tool_response("unsupported", False, "Claim is wrong.")
        meta = MetaJudge(client)
        verdict, _ = asyncio.run(
            meta.arbitrate(_make_ldp(), _make_verdicts("unsupported", "partial", "unsupported"))
        )
        assert verdict == "unsupported"
