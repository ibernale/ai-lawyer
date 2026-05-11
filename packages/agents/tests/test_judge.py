"""Tests for LegalJudge — verdicts, scores, iteration cap circuit breaker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lex_agents_agents.base_agent import AgentMetadata, AgentResponse
from lex_agents_agents.core.judge import _MAX_ITERATIONS, LegalJudge
from lex_agents_agents.shared.definition_of_done import DefinitionOfDone, JudgeVerdict


def _make_client() -> MagicMock:
    return MagicMock()


def _make_judge(client: MagicMock) -> LegalJudge:
    with patch("lex_agents_agents.core.judge.load_prompt") as mock_load:
        cfg = MagicMock()
        cfg.version = 1
        cfg.content_hash = "deadbeef1234"
        cfg.model = "claude-opus-4-7"
        cfg.max_tokens = 2048
        cfg.body = "You are a judge."
        mock_load.return_value = cfg
        return LegalJudge(client)


def _make_response(text: str = "Respuesta completa") -> AgentResponse:
    return AgentResponse(
        trace_id="test-trace",
        answer_text=text,
        citations=[],
        verification=None,
        metadata=AgentMetadata(
            trace_id="test-trace",
            prompt_name="especialistas/regulatorio_bancario_ue_es",
            prompt_version=1,
            prompt_hash="abc123",
            model="claude-opus-4-7",
            input_tokens=300,
            output_tokens=500,
            latency_ms=800.0,
            cost_estimate_usd=0.042,
        ),
        query_rewritten="consulta",
    )


def _make_tool_response(verdict: str, scores: dict | None = None, gaps: list | None = None) -> MagicMock:
    if scores is None:
        scores = {
            "factual_support": 0.9,
            "completeness": 0.8,
            "jurisdictional_correctness": 0.85,
            "caveat_appropriateness": 0.9,
            "internal_consistency": 0.95,
        }
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "verdict": verdict,
        "scores": scores,
        "gaps": gaps or [],
        "iteration_brief": f"Evaluación: {verdict}",
    }
    resp = MagicMock()
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    resp.content = [tool_block]
    return resp


class TestJudgeVerdicts:
    def test_publish_verdict(self) -> None:
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response("publish")

        dod = DefinitionOfDone(must_cover_concepts=["CET1"])
        verdict = judge.judge([_make_response()], dod, iteration=1)

        assert isinstance(verdict, JudgeVerdict)
        assert verdict.verdict == "publish"
        assert verdict.iteration == 1
        assert verdict.scores["factual_support"] == 0.9

    def test_revise_verdict(self) -> None:
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response(
            "revise", gaps=["falta análisis arts 107 CRR"]
        )

        dod = DefinitionOfDone(must_cover_concepts=["grandes riesgos"])
        verdict = judge.judge([_make_response()], dod, iteration=1)

        assert verdict.verdict == "revise"
        assert len(verdict.gaps) == 1
        assert "arts 107 CRR" in verdict.gaps[0]

    def test_reject_verdict(self) -> None:
        client = _make_client()
        judge = _make_judge(client)
        low_scores = {
            "factual_support": 0.1,
            "completeness": 0.1,
            "jurisdictional_correctness": 0.1,
            "caveat_appropriateness": 0.1,
            "internal_consistency": 0.1,
        }
        client.messages_create.return_value = _make_tool_response("reject", scores=low_scores)

        dod = DefinitionOfDone()
        verdict = judge.judge([_make_response()], dod, iteration=1)

        assert verdict.verdict == "reject"


class TestIterationCapCircuitBreaker:
    def test_iteration_cap_forces_publish(self) -> None:
        """At iter >= MAX_ITERATIONS, 'revise' must be overridden to 'publish'."""
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response(
            "revise", gaps=["brecha pendiente"]
        )

        dod = DefinitionOfDone()
        verdict = judge.judge([_make_response()], dod, iteration=_MAX_ITERATIONS)

        assert verdict.verdict == "publish"
        assert "verification_partial=True" in verdict.iteration_brief
        assert "brecha pendiente" in verdict.iteration_brief

    def test_iteration_cap_only_applies_to_revise(self) -> None:
        """At iter >= MAX_ITERATIONS, 'publish' should remain 'publish'."""
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response("publish")

        dod = DefinitionOfDone()
        verdict = judge.judge([_make_response()], dod, iteration=_MAX_ITERATIONS)

        assert verdict.verdict == "publish"
        assert "verification_partial" not in verdict.iteration_brief

    def test_iteration_cap_only_applies_to_reject_if_reject(self) -> None:
        """At iter >= MAX_ITERATIONS, 'reject' should remain 'reject'."""
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response("reject")

        dod = DefinitionOfDone()
        verdict = judge.judge([_make_response()], dod, iteration=_MAX_ITERATIONS)

        assert verdict.verdict == "reject"


class TestJudgeFallbacks:
    def test_api_error_force_publish(self) -> None:
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.side_effect = Exception("API timeout")

        dod = DefinitionOfDone()
        verdict = judge.judge([_make_response()], dod, iteration=1)

        assert verdict.verdict == "publish"
        assert "judge_unavailable:api_error" in verdict.gaps

    def test_no_tool_use_force_publish(self) -> None:
        client = _make_client()
        judge = _make_judge(client)
        resp = MagicMock()
        resp.usage = MagicMock(input_tokens=50, output_tokens=10)
        resp.content = [MagicMock(type="text")]
        client.messages_create.return_value = resp

        dod = DefinitionOfDone()
        verdict = judge.judge([_make_response()], dod, iteration=1)

        assert verdict.verdict == "publish"
        assert "judge_unavailable:no_tool_use" in verdict.gaps

    def test_chaos_always_reject_leads_to_forced_publish(self) -> None:
        """Simulate always-rejecting judge: iter 1 → revise, iter 2 → revise → forced publish."""
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response(
            "revise", gaps=["sigue faltando"]
        )

        dod = DefinitionOfDone()

        v1 = judge.judge([_make_response()], dod, iteration=1)
        assert v1.verdict == "revise"

        v2 = judge.judge([_make_response()], dod, iteration=2)
        assert v2.verdict == "publish"
        assert "verification_partial=True" in v2.iteration_brief

    def test_multi_response_combined(self) -> None:
        """Judge receives multiple AgentResponses and combines them."""
        client = _make_client()
        judge = _make_judge(client)
        client.messages_create.return_value = _make_tool_response("publish")

        responses = [_make_response("Rama 1"), _make_response("Rama 2")]
        dod = DefinitionOfDone()
        verdict = judge.judge(responses, dod, iteration=1)

        assert verdict.verdict == "publish"
        # Verify LLM was called with both responses combined
        call_args = client.messages_create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "Rama 1" in user_content
        assert "Rama 2" in user_content
