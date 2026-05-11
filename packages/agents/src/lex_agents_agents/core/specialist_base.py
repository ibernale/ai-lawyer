"""Abstract base class for all specialist (Maker) agents."""

from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from typing import ClassVar

import structlog
from opentelemetry import trace

from lex_agents_rag.assembler import AssembledContext
from lex_agents_shared.anthropic_client import AnthropicClientWrapper, MODEL_OPUS

from lex_agents_agents.base_agent import AgentMetadata, AgentResponse, BaseAgent
from lex_agents_agents.prompt_loader import load_prompt
from lex_agents_agents.shared.definition_of_done import BranchTask

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_INPUT_TOKEN_COST_PER_M = 15.0
_OUTPUT_TOKEN_COST_PER_M = 75.0


class BaseSpecialist(BaseAgent):
    """Async Maker agent base. Subclasses declare branch_id and prompt_name."""

    branch_id: ClassVar[str]
    prompt_name: ClassVar[str]
    prompt_version: ClassVar[int] = 1

    def __init__(
        self,
        client: AnthropicClientWrapper,
        prompt_version: int | None = None,
    ) -> None:
        self._client = client
        v = prompt_version if prompt_version is not None else self.__class__.prompt_version
        self._cfg = load_prompt(self.prompt_name, version=v)
        logger.info(
            "specialist_prompt_loaded",
            branch=self.branch_id,
            version=self._cfg.version,
            hash=self._cfg.content_hash[:12],
        )

    # Sync run() satisfies BaseAgent ABC — delegates to async implementation.
    # Uses asyncio.run() to create a fresh event loop, safe from any async context.
    def run(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
    ) -> AgentResponse:
        return asyncio.run(self.run_async(query, assembled, trace_id))

    @abstractmethod
    async def run_async(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
        sub_task: BranchTask | None = None,
    ) -> AgentResponse: ...

    def _invoke(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
        span_name: str | None = None,
        extra_caveat: str | None = None,
    ) -> AgentResponse:
        """Common LLM call pattern shared by all specialists."""
        with tracer.start_as_current_span(span_name or f"specialist.{self.branch_id}") as span:
            span.set_attribute("specialist.branch", self.branch_id)
            span.set_attribute("specialist.prompt_version", self._cfg.version)
            span.set_attribute("model", MODEL_OPUS)

            user_content = f"{assembled.context_text}\n\n---\n\nConsulta: {query}"
            if extra_caveat:
                user_content += f"\n\n{extra_caveat}"

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

            text_block = next(
                (b for b in resp.content if getattr(b, "type", None) == "text"), None
            )
            if text_block is None:
                logger.error(
                    "specialist_empty_response",
                    branch=self.branch_id,
                    stop_reason=getattr(resp, "stop_reason", "unknown"),
                )
                answer_text = (
                    "No se pudo generar respuesta para esta rama. "
                    "Consulte los servicios jurídicos especializados."
                )
            else:
                answer_text = text_block.text  # type: ignore[union-attr]
            logger.info(
                "specialist_response",
                branch=self.branch_id,
                prompt_version=self._cfg.version,
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
