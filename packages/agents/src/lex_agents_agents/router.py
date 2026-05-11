"""Query router — classifies incoming queries and returns a RoutingDecision."""

from __future__ import annotations

import json
import time

import structlog
from opentelemetry import trace

from lex_agents_shared.anthropic_client import AnthropicClientWrapper

from .base_agent import RoutingDecision
from .prompt_loader import load_prompt

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_ROUTE_TOOL = {
    "name": "route_query",
    "description": "Return the routing decision for the incoming legal query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "enum": ["regulatorio_bancario_ue_es", "fuera_de_alcance"],
            },
            "jurisdictions": {
                "type": "array",
                "items": {"type": "string", "enum": ["ES", "EU"]},
            },
            "output_type": {
                "type": "string",
                "enum": ["dictamen", "nota", "memo_comite", "analisis_riesgo"],
                "default": "dictamen",
            },
            "depth": {
                "type": "string",
                "enum": ["shallow", "standard", "deep"],
                "default": "standard",
            },
            "sub_queries": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
        },
        "required": ["branch", "jurisdictions", "output_type", "depth", "sub_queries"],
    },
}

_DEFAULT_DECISION = RoutingDecision(
    branch="fuera_de_alcance",
    jurisdictions=[],
    output_type="dictamen",
    depth="standard",
    sub_queries=[],
)


class QueryRouter:
    def __init__(self, client: AnthropicClientWrapper, prompt_version: int = 1) -> None:
        self._client = client
        self._cfg = load_prompt("router", version=prompt_version)
        logger.info(
            "router_prompt_loaded",
            version=self._cfg.version,
            hash=self._cfg.content_hash[:12],
        )

    def route(self, query: str) -> RoutingDecision:
        with tracer.start_as_current_span("orchestrator.route") as span:
            t0 = time.monotonic()
            span.set_attribute("prompt.version", self._cfg.version)
            span.set_attribute("prompt.hash", self._cfg.content_hash[:12])
            span.set_attribute("model", self._cfg.model)

            try:
                resp = self._client.messages_create(
                    model=self._cfg.model,
                    max_tokens=self._cfg.max_tokens,
                    system=self._cfg.body,
                    tools=[_ROUTE_TOOL],
                    tool_choice={"type": "any"},
                    messages=[{"role": "user", "content": query}],
                )
            except Exception:
                logger.exception("router_api_error", query_snippet=query[:80])
                span.set_attribute("routing.branch", "fuera_de_alcance")
                span.set_attribute("routing.error", True)
                return _DEFAULT_DECISION

            latency = (time.monotonic() - t0) * 1000
            span.set_attribute("latency_ms", round(latency))
            span.set_attribute("tokens.in", resp.usage.input_tokens)
            span.set_attribute("tokens.out", resp.usage.output_tokens)

            tool_use_block = next(
                (b for b in resp.content if b.type == "tool_use"),
                None,
            )
            if tool_use_block is None:
                logger.warning("router_no_tool_use", content_types=[b.type for b in resp.content])
                span.set_attribute("routing.branch", "fuera_de_alcance")
                return _DEFAULT_DECISION

            try:
                raw: dict = tool_use_block.input if isinstance(tool_use_block.input, dict) else json.loads(tool_use_block.input)  # type: ignore[arg-type]
                decision = RoutingDecision(
                    branch=raw["branch"],
                    jurisdictions=raw.get("jurisdictions", []),
                    output_type=raw.get("output_type", "dictamen"),
                    depth=raw.get("depth", "standard"),
                    sub_queries=raw.get("sub_queries", []),
                )
            except Exception:
                logger.exception("router_parse_error", raw=tool_use_block.input)
                span.set_attribute("routing.branch", "fuera_de_alcance")
                return _DEFAULT_DECISION

            span.set_attribute("routing.branch", decision.branch)
            span.set_attribute("routing.depth", decision.depth)
            logger.info(
                "query_routed",
                branch=decision.branch,
                depth=decision.depth,
                latency_ms=round(latency),
            )
            return decision
