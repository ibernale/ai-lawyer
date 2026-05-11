"""Specialist agent for EU+ES banking regulation queries."""

from __future__ import annotations

import time

import structlog
from opentelemetry import trace

from lex_agents_rag.assembler import AssembledContext
from lex_agents_shared.anthropic_client import AnthropicClientWrapper, MODEL_OPUS

from .base_agent import AgentMetadata, AgentResponse, BaseAgent
from .prompt_loader import load_prompt

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_INPUT_TOKEN_COST_PER_M = 15.0   # USD per 1M input tokens (Opus 4.7)
_OUTPUT_TOKEN_COST_PER_M = 75.0  # USD per 1M output tokens (Opus 4.7)


class RegulatorioBancarioAgent(BaseAgent):
    def __init__(self, client: AnthropicClientWrapper, prompt_version: int = 1) -> None:
        self._client = client
        self._cfg = load_prompt("especialistas/regulatorio_bancario_ue_es", version=prompt_version)
        logger.info(
            "specialist_prompt_loaded",
            name=self._cfg.name,
            version=self._cfg.version,
            hash=self._cfg.content_hash[:12],
        )

    def run(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
    ) -> AgentResponse:
        with tracer.start_as_current_span("orchestrator.specialist") as span:
            span.set_attribute("specialist.name", "regulatorio_bancario_ue_es")
            span.set_attribute("specialist.prompt_version", self._cfg.version)
            span.set_attribute("model", MODEL_OPUS)

            user_content = f"{assembled.context_text}\n\n---\n\nConsulta: {query}"
            t0 = time.monotonic()

            resp = self._client.messages_create(
                model=MODEL_OPUS,
                max_tokens=self._cfg.max_tokens,
                system=self._cfg.body,
                messages=[{"role": "user", "content": user_content}],
            )

            latency = (time.monotonic() - t0) * 1000
            in_tok = resp.usage.input_tokens
            out_tok = resp.usage.output_tokens
            cost = (in_tok / 1_000_000 * _INPUT_TOKEN_COST_PER_M) + (
                out_tok / 1_000_000 * _OUTPUT_TOKEN_COST_PER_M
            )

            span.set_attribute("tokens.in", in_tok)
            span.set_attribute("tokens.out", out_tok)
            span.set_attribute("latency_ms", round(latency))
            span.set_attribute("cost_usd", round(cost, 6))
            span.set_attribute("prompt.hash", self._cfg.content_hash[:12])

            answer_text = resp.content[0].text  # type: ignore[union-attr]

            logger.info(
                "specialist_response",
                specialist="regulatorio_bancario_ue_es",
                prompt_version=self._cfg.version,
                prompt_hash=self._cfg.content_hash[:12],
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=round(latency),
                cost_usd=round(cost, 6),
            )

            return AgentResponse(
                trace_id=trace_id,
                answer_text=answer_text,
                citations=assembled.citation_mapping,
                verification=None,
                metadata=AgentMetadata(
                    trace_id=trace_id,
                    prompt_name=self._cfg.name,
                    prompt_version=self._cfg.version,
                    prompt_hash=self._cfg.content_hash,
                    model=MODEL_OPUS,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    latency_ms=latency,
                    cost_estimate_usd=cost,
                ),
                query_rewritten=query,
            )
