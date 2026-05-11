"""Tests for JudgePanel and consensus / meta-judge arbitration paths."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lex_agents_evals_advanced.lemaj.panel import JudgePanel, _convert_verdict
from lex_agents_evals_advanced.lemaj.judges.base import (
    BaseJudge,
    JudgeDimensions as BaseDims,
    SingleJudgeVerdict as BaseVerdict,
)
from lex_agents_evals_advanced.types import LegalDataPoint


def _make_ldp(ldp_id: str = "CASE-001-LDP-1") -> LegalDataPoint:
    return LegalDataPoint(
        ldp_id=ldp_id,
        claim_text="El ratio mínimo CRR es 8%.",
        claim_type="factual",
        supporting_refs=["REF:1"],
        jurisdiction_scope="EU",
        context="Según el artículo 92 CRR...",
    )


def _base_verdict(judge_id: str, overall: str = "supported") -> BaseVerdict:
    return BaseVerdict(
        judge_id=judge_id,
        model="claude-opus-4-7-20250514",
        ldp_id="CASE-001-LDP-1",
        dimensions=BaseDims(
            factual_support="supported",
            normative_accuracy="supported",
            jurisdictional_correctness="supported",
            completeness_partial="supported",
            caveat_appropriateness="supported",
        ),
        overall=overall,
        reasoning="OK",
    )


def _stub_judge(jid: str, overall: str = "supported") -> type[BaseJudge]:
    """Return a stub judge class that returns a fixed verdict."""
    _jid = jid
    _overall = overall

    class StubJudge(BaseJudge):
        model = "stub-model"
        temperature = 0.0
        prompt_version_key = "A"

        def __init__(self, client):
            self._client = client
            self._system_body = "stub"

        async def evaluate(self, **kwargs) -> BaseVerdict:
            return _base_verdict(_jid, _overall)

    StubJudge.judge_id = _jid  # type: ignore[attr-defined]
    return StubJudge


class TestConvertVerdict:
    def test_converts_dimensions_and_overall(self):
        bv = _base_verdict("A", "partial")
        sv = _convert_verdict(bv)
        assert sv.judge_id == "A"
        assert sv.overall == "partial"
        assert sv.dimensions.factual_support == "supported"


class TestJudgePanelConsensus:
    def test_all_agree_no_meta_judge(self):
        client = MagicMock()
        judges = [_stub_judge("A"), _stub_judge("B"), _stub_judge("C")]
        panel = JudgePanel(client, judges=judges)

        ldp = _make_ldp()
        result = asyncio.run(panel.evaluate_ldp(ldp, "context"))

        assert result.final_verdict == "supported"
        assert result.meta_judge_used is False
        assert len(result.judge_verdicts) == 3

    def test_all_partial_no_meta_judge(self):
        client = MagicMock()
        judges = [
            _stub_judge("A", "partial"),
            _stub_judge("B", "partial"),
            _stub_judge("C", "partial"),
        ]
        panel = JudgePanel(client, judges=judges)
        result = asyncio.run(panel.evaluate_ldp(_make_ldp(), "ctx"))
        assert result.final_verdict == "partial"
        assert result.meta_judge_used is False

    def test_disagreement_triggers_meta_judge(self):
        client = MagicMock()
        judges = [
            _stub_judge("A", "supported"),
            _stub_judge("B", "partial"),
            _stub_judge("C", "unsupported"),
        ]
        panel = JudgePanel(client, judges=judges)

        # Patch meta_judge to return "partial"
        mock_meta = MagicMock()
        mock_meta.arbitrate = AsyncMock(return_value=("partial", "Meta reasoning"))
        panel._meta_judge = mock_meta

        result = asyncio.run(panel.evaluate_ldp(_make_ldp(), "ctx"))

        assert result.meta_judge_used is True
        assert result.final_verdict == "partial"
        mock_meta.arbitrate.assert_called_once()

    def test_return_exceptions_partial_failure(self):
        """If one judge raises, remaining verdicts are still used."""
        client = MagicMock()

        class FailingJudge(BaseJudge):
            model = "stub"
            temperature = 0.0
            prompt_version_key = "A"

            def __init__(self, c):
                self._client = c
                self._system_body = ""

            async def evaluate(self, **kwargs) -> BaseVerdict:
                raise RuntimeError("Judge B crashed")

        FailingJudge.judge_id = "B"  # type: ignore[attr-defined]

        judges = [_stub_judge("A", "supported"), FailingJudge, _stub_judge("C", "supported")]
        panel = JudgePanel(client, judges=judges)
        result = asyncio.run(panel.evaluate_ldp(_make_ldp(), "ctx"))

        # Should still get a verdict from A and C
        assert result.final_verdict in ("supported", "partial", "unsupported", "review_required")
        assert len(result.judge_verdicts) == 2  # only A and C succeeded

    def test_all_judges_fail_returns_review_required(self):
        client = MagicMock()

        class AlwaysFail(BaseJudge):
            model = "stub"
            temperature = 0.0
            prompt_version_key = "A"

            def __init__(self, c):
                self._client = c
                self._system_body = ""

            async def evaluate(self, **kwargs) -> BaseVerdict:
                raise RuntimeError("always fails")

        AlwaysFail.judge_id = "X"  # type: ignore[attr-defined]

        panel = JudgePanel(client, judges=[AlwaysFail, AlwaysFail, AlwaysFail])
        result = asyncio.run(panel.evaluate_ldp(_make_ldp(), "ctx"))
        assert result.final_verdict == "review_required"


class TestJudgePanelEvaluateAll:
    def test_sequential_evaluation(self):
        client = MagicMock()
        judges = [_stub_judge("A"), _stub_judge("B"), _stub_judge("C")]
        panel = JudgePanel(client, judges=judges)
        ldps = [_make_ldp(f"CASE-001-LDP-{i}") for i in range(1, 4)]
        results = asyncio.run(panel.evaluate_all(ldps, "ctx"))
        assert len(results) == 3
        assert all(r.final_verdict == "supported" for r in results)
