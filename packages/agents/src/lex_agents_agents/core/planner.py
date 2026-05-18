"""Planner agent — decomposes queries into branch sub-tasks with DefinitionOfDone."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import structlog
from lex_agents_shared.anthropic_client import MODEL_OPUS, AnthropicClientWrapper
from opentelemetry import trace

from lex_agents_agents.prompt_loader import load_prompt
from lex_agents_agents.shared.definition_of_done import (
    BranchTask,
    DefinitionOfDone,
    PlannerOutput,
)

if TYPE_CHECKING:
    from lex_agents_memory import MemoryInjector

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_PLAN_TOOL = {
    "name": "plan_query",
    "description": "Produce a structured execution plan for the legal query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "branches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "priority": {"type": "integer"},
                        "weight": {"type": "number"},
                    },
                    "required": ["name", "priority", "weight"],
                },
            },
            "jurisdictions": {"type": "array", "items": {"type": "string"}},
            "output_type": {
                "type": "string",
                "enum": ["dictamen", "nota", "memo_comite", "analisis_riesgo"],
            },
            "depth": {
                "type": "string",
                "enum": ["shallow", "standard", "deep"],
            },
            "sub_tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "branch": {"type": "string"},
                        "priority": {"type": "integer"},
                        "weight": {"type": "number"},
                        "query": {"type": "string"},
                        "expected_artifacts": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "branch", "priority", "weight", "query", "expected_artifacts"],
                },
            },
            "definition_of_done": {
                "type": "object",
                "properties": {
                    "must_cover_concepts": {"type": "array", "items": {"type": "string"}},
                    "must_consider_jurisdictions": {"type": "array", "items": {"type": "string"}},
                    "must_address_caveats": {"type": "array", "items": {"type": "string"}},
                    "out_of_scope": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "must_cover_concepts",
                    "must_consider_jurisdictions",
                    "must_address_caveats",
                    "out_of_scope",
                ],
            },
        },
        "required": [
            "branches", "jurisdictions", "output_type", "depth",
            "sub_tasks", "definition_of_done",
        ],
    },
}

_DEFAULT_OUTPUT = PlannerOutput(
    branches=[{"name": "fuera_de_alcance", "priority": 1, "weight": 1.0}],
    jurisdictions=[],
    output_type="dictamen",
    depth="standard",
    sub_tasks=[],
    definition_of_done=DefinitionOfDone(),
)


class LegalPlanner:
    def __init__(
        self,
        client: AnthropicClientWrapper,
        prompt_version: int = 1,
        memory_injector: MemoryInjector | None = None,
    ) -> None:
        self._client = client
        self._cfg = load_prompt("planner", version=prompt_version)
        self._memory_injector = memory_injector
        logger.info(
            "planner_prompt_loaded",
            version=self._cfg.version,
            hash=self._cfg.content_hash[:12],
            memory_enabled=memory_injector is not None,
        )

    def plan(
        self,
        query: str,
        jurisdiction_hint: str | None = None,
        output_type: str | None = None,
        depth_hint: str | None = None,
    ) -> PlannerOutput:
        with tracer.start_as_current_span("planner.plan") as span:
            span.set_attribute("prompt.version", self._cfg.version)
            span.set_attribute("model", MODEL_OPUS)

            user_msg = query
            if jurisdiction_hint:
                user_msg += f"\n\nJurisdicción indicada: {jurisdiction_hint}"
            if output_type:
                user_msg += f"\nTipo de output preferido: {output_type}"
            if depth_hint:
                user_msg += f"\nProfundidad de análisis requerida: {depth_hint}"

            if self._memory_injector is not None:
                jurisdictions = [jurisdiction_hint] if jurisdiction_hint else []
                memory_ctx = self._memory_injector.build_context(
                    query=query,
                    jurisdictions=jurisdictions,
                    output_type=output_type,
                )
                if memory_ctx:
                    user_msg = memory_ctx + "\n\n---\n\n" + user_msg
                    span.set_attribute("memory.injected", True)
                    span.set_attribute("memory.context_len", len(memory_ctx))
                else:
                    span.set_attribute("memory.injected", False)

            t0 = time.monotonic()
            try:
                resp = self._client.messages_create(
                    model=self._cfg.model,
                    max_tokens=self._cfg.max_tokens,
                    system=self._cfg.body,
                    tools=[_PLAN_TOOL],
                    tool_choice={"type": "any"},
                    messages=[{"role": "user", "content": user_msg}],
                )
            except Exception:
                logger.exception("planner_api_error", query_snippet=query[:80])
                return _DEFAULT_OUTPUT

            latency = (time.monotonic() - t0) * 1000
            span.set_attribute("latency_ms", round(latency))
            span.set_attribute("tokens.in", resp.usage.input_tokens)
            span.set_attribute("tokens.out", resp.usage.output_tokens)

            tool_block = next(
                (b for b in resp.content if b.type == "tool_use"), None
            )
            if tool_block is None:
                logger.warning("planner_no_tool_use")
                return _DEFAULT_OUTPUT

            try:
                raw: dict[str, Any] = (
                    tool_block.input
                    if isinstance(tool_block.input, dict)
                    else json.loads(tool_block.input)
                )

                # Claude occasionally returns nested structures as JSON strings
                # inside tool-use parameters — parse them defensively.
                sub_tasks_raw = raw.get("sub_tasks", [])
                if isinstance(sub_tasks_raw, str):
                    sub_tasks_raw = json.loads(sub_tasks_raw)

                sub_tasks = [
                    BranchTask(
                        id=t["id"],
                        branch=t["branch"],
                        priority=int(t["priority"]),
                        weight=float(t["weight"]),
                        query=t["query"],
                        expected_artifacts=t.get("expected_artifacts", []),
                    )
                    for t in sub_tasks_raw
                ]

                dod_raw = raw.get("definition_of_done", {})
                if isinstance(dod_raw, str):
                    dod_raw = json.loads(dod_raw)
                dod = DefinitionOfDone(
                    must_cover_concepts=dod_raw.get("must_cover_concepts", []),
                    must_consider_jurisdictions=dod_raw.get("must_consider_jurisdictions", []),
                    must_address_caveats=dod_raw.get("must_address_caveats", []),
                    out_of_scope=dod_raw.get("out_of_scope", []),
                )

                output = PlannerOutput(
                    branches=raw.get("branches", []),
                    jurisdictions=raw.get("jurisdictions", []),
                    output_type=raw.get("output_type", output_type or "dictamen"),
                    depth=depth_hint or raw.get("depth", "standard"),
                    sub_tasks=sub_tasks,
                    definition_of_done=dod,
                )

            except Exception:
                logger.exception("planner_parse_error")
                return _DEFAULT_OUTPUT

            logger.info(
                "planner_complete",
                branches=[b["name"] for b in output.branches],
                depth=output.depth,
                n_sub_tasks=len(output.sub_tasks),
                latency_ms=round(latency),
            )
            return output
