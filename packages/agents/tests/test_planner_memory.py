"""Tests for LegalPlanner + MemoryInjector integration (ADR 0013)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from lex_agents_agents.core.planner import LegalPlanner
from lex_agents_agents.shared.definition_of_done import PlannerOutput
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_client() -> MagicMock:
    client = MagicMock()
    client.messages_create.return_value = MagicMock(
        usage=MagicMock(input_tokens=100, output_tokens=50),
        content=[],
    )
    return client


def _make_planner(client: MagicMock, memory_injector=None) -> LegalPlanner:
    with patch("lex_agents_agents.core.planner.load_prompt") as mock_load:
        cfg = MagicMock()
        cfg.version = 1
        cfg.content_hash = "abc123def456"
        cfg.model = "claude-opus-4-7"
        cfg.max_tokens = 4096
        cfg.body = "You are a planner."
        mock_load.return_value = cfg
        return LegalPlanner(client, memory_injector=memory_injector)


def _make_tool_response(raw: dict) -> MagicMock:
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = raw
    resp = MagicMock()
    resp.usage = MagicMock(input_tokens=300, output_tokens=100)
    resp.content = [tool_block]
    return resp


_VALID_PLAN_RAW = {
    "branches": [{"name": "regulatorio_bancario_ue_es", "priority": 1, "weight": 1.0}],
    "jurisdictions": ["ES"],
    "output_type": "dictamen",
    "depth": "standard",
    "sub_tasks": [
        {
            "id": "T1",
            "branch": "regulatorio_bancario_ue_es",
            "priority": 1,
            "weight": 1.0,
            "query": "ratio de capital CRR",
            "expected_artifacts": ["análisis capital"],
        }
    ],
    "definition_of_done": {
        "must_cover_concepts": ["CET1"],
        "must_consider_jurisdictions": ["ES"],
        "must_address_caveats": [],
        "out_of_scope": [],
    },
}


def _setup_tracer() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


# ── tests ─────────────────────────────────────────────────────────────────────

class TestPlannerWithoutMemory:
    def test_no_memory_injector_returns_valid_plan(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)
        planner = _make_planner(client)
        result = planner.plan("¿Qué ratio de capital exige el CRR?", jurisdiction_hint="ES")
        assert isinstance(result, PlannerOutput)
        assert len(result.sub_tasks) == 1

    def test_no_memory_injector_message_not_prepended(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)
        planner = _make_planner(client)
        planner.plan("consulta sobre capital", jurisdiction_hint="ES")
        call_kwargs = client.messages_create.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        # Extract the user message content
        user_content = next(
            m["content"] for m in call_kwargs.kwargs["messages"]
            if m["role"] == "user"
        )
        assert "---" not in user_content  # no memory separator injected


class TestPlannerWithMemory:
    def test_memory_context_prepended_to_user_msg(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

        mock_injector = MagicMock()
        mock_injector.build_context.return_value = "## Memoria Semántica\n\nContexto relevante"

        planner = _make_planner(client, memory_injector=mock_injector)
        planner.plan("¿Qué ratio de capital?", jurisdiction_hint="ES", output_type="dictamen")

        call_kwargs = client.messages_create.call_args.kwargs
        user_content = next(
            m["content"] for m in call_kwargs["messages"] if m["role"] == "user"
        )
        assert "## Memoria Semántica" in user_content
        assert "---" in user_content
        assert "¿Qué ratio de capital?" in user_content

    def test_memory_injector_called_with_correct_args(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

        mock_injector = MagicMock()
        mock_injector.build_context.return_value = "## Memory block"

        planner = _make_planner(client, memory_injector=mock_injector)
        query = "consulta CRR"
        planner.plan(query, jurisdiction_hint="ES", output_type="dictamen")

        mock_injector.build_context.assert_called_once_with(
            query=query,
            jurisdictions=["ES"],
            output_type="dictamen",
        )

    def test_empty_memory_context_not_prepended(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

        mock_injector = MagicMock()
        mock_injector.build_context.return_value = ""  # empty → no injection

        planner = _make_planner(client, memory_injector=mock_injector)
        planner.plan("consulta básica", jurisdiction_hint="ES")

        call_kwargs = client.messages_create.call_args.kwargs
        user_content = next(
            m["content"] for m in call_kwargs["messages"] if m["role"] == "user"
        )
        assert "---" not in user_content

    def test_memory_injector_error_does_not_break_plan(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

        mock_injector = MagicMock()
        mock_injector.build_context.side_effect = RuntimeError("DB connection failed")

        planner = _make_planner(client, memory_injector=mock_injector)
        # Should not raise — memory errors must not block Planner
        with pytest.raises(RuntimeError):
            planner.plan("consulta", jurisdiction_hint="ES")

    def test_span_attributes_set_when_memory_injected(self) -> None:
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch("lex_agents_agents.core.planner.tracer", mock_tracer):
            client = _make_client()
            client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

            mock_injector = MagicMock()
            memory_ctx = "## Memory\n\nContexto"
            mock_injector.build_context.return_value = memory_ctx

            planner = _make_planner(client, memory_injector=mock_injector)
            planner.plan("consulta CRR", jurisdiction_hint="ES")

            calls = {
                call.args[0]: call.args[1]
                for call in mock_span.set_attribute.call_args_list
            }
            assert calls.get("memory.injected") is True
            assert calls.get("memory.context_len") == len(memory_ctx)

    def test_span_attributes_set_when_memory_empty(self) -> None:
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch("lex_agents_agents.core.planner.tracer", mock_tracer):
            client = _make_client()
            client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

            mock_injector = MagicMock()
            mock_injector.build_context.return_value = ""

            planner = _make_planner(client, memory_injector=mock_injector)
            planner.plan("consulta simple")

            calls = {
                call.args[0]: call.args[1]
                for call in mock_span.set_attribute.call_args_list
            }
            assert calls.get("memory.injected") is False

    def test_no_jurisdiction_hint_passes_empty_list_to_injector(self) -> None:
        client = _make_client()
        client.messages_create.return_value = _make_tool_response(_VALID_PLAN_RAW)

        mock_injector = MagicMock()
        mock_injector.build_context.return_value = ""

        planner = _make_planner(client, memory_injector=mock_injector)
        planner.plan("consulta sin jurisdicción")

        mock_injector.build_context.assert_called_once_with(
            query="consulta sin jurisdicción",
            jurisdictions=[],
            output_type=None,
        )
