"""Query router v1 — classifies incoming queries and returns a RoutingDecision.

Used by the shallow path in OrchestratorV2. Multi-branch routing is handled by
LegalPlanner (standard/deep paths).
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from opentelemetry import trace

from lex_agents_agents.base_agent import RoutingDecision
from lex_agents_agents.prompt_loader import load_prompt

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_VALID_BRANCHES = {
    "regulatorio_bancario_ue_es",
    "datos_personales_rgpd",
    "laboral",
    "mercantil_societario",
    "penal_economico",
    "administrativo",
    "aml_compliance",
    "psd2_payment_services",
    "fuera_de_alcance",
}

_ROUTE_TOOL = {
    "name": "route_query",
    "description": "Return the routing decision for the incoming legal query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "branches": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": sorted(_VALID_BRANCHES),
                },
                "minItems": 1,
                "maxItems": 3,
                "description": (
                    "Branch identifiers to activate. Use ['fuera_de_alcance'] when out of scope."
                ),
            },
            "depth": {
                "type": "string",
                "enum": ["shallow", "standard", "deep"],
                "default": "standard",
            },
            "sub_queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "branch": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["branch", "query"],
                },
                "description": "Only populate when the query contains clearly separable sub-questions.",
            },
            "rationale": {
                "type": "string",
                "description": "One-sentence explanation of the routing decision (internal).",
            },
        },
        "required": ["branches", "depth", "rationale"],
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
    def __init__(self, client: AnthropicClientWrapper, prompt_version: int = 2) -> None:
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
                (b for b in resp.content if b.type == "tool_use"), None
            )
            if tool_use_block is None:
                logger.warning("router_no_tool_use")
                return _DEFAULT_DECISION

            try:
                raw: dict[str, Any] = (
                    tool_use_block.input
                    if isinstance(tool_use_block.input, dict)
                    else json.loads(tool_use_block.input)
                )
                # v2 prompt returns `branches` (array); take first valid branch for
                # RoutingDecision.branch (orchestrator uses the primary branch only;
                # multi-branch parallelism is handled by LegalPlanner on deeper paths).
                branches_raw: list[str] = raw.get("branches", ["fuera_de_alcance"])
                primary_branch = next(
                    (b for b in branches_raw if b in _VALID_BRANCHES),
                    "fuera_de_alcance",
                )
                # Preserve raw branch list for span metadata / future multi-branch support
                all_branches = [b for b in branches_raw if b in _VALID_BRANCHES] or ["fuera_de_alcance"]
                decision = RoutingDecision(
                    branch=primary_branch,
                    jurisdictions=raw.get("jurisdictions", []),
                    output_type=raw.get("output_type", "dictamen"),
                    depth=raw.get("depth", "standard"),
                    sub_queries=raw.get("sub_queries", []),
                )
            except Exception:
                logger.exception("router_parse_error")
                return _DEFAULT_DECISION

            span.set_attribute("routing.branch", decision.branch)
            span.set_attribute("routing.branches", ",".join(all_branches))
            span.set_attribute("routing.depth", decision.depth)
            logger.info(
                "query_routed",
                branch=decision.branch,
                all_branches=all_branches,
                depth=decision.depth,
                latency_ms=round(latency),
            )
            return decision
