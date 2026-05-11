"""Orchestrator — coordinates RAG retrieval, specialist agents, and verification."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from opentelemetry import trace
from pydantic import BaseModel

from lex_agents_rag.assembler import ContextAssembler
from lex_agents_rag.query_rewriter import LegalQueryRewriter
from lex_agents_rag.reranker import BaseReranker
from lex_agents_rag.retriever import HybridRetriever, SearchFilters
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from lex_agents_shared.types import CitationMapping, VerificationReport

from .base_agent import AgentMetadata, AgentResponse, RoutingDecision
from .regulatorio_bancario import RegulatorioBancarioAgent
from .router import QueryRouter
from .synthesizer import SynthesizerAgent

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

_OUT_OF_SCOPE_ANSWER = (
    "La consulta planteada está fuera del ámbito de este sistema, "
    "que cubre exclusivamente regulación bancaria española y comunitaria (UE+ES). "
    "Para consultas sobre otras materias, le recomendamos acudir a los servicios "
    "jurídicos especializados correspondientes."
)


class ConsultRequest(BaseModel):
    query: str
    jurisdiction_hint: str | None = None
    output_type: str | None = None


class ConsultResponse(BaseModel):
    trace_id: str
    answer: str
    citations: list[CitationMapping]
    verification: VerificationReport | None
    query_rewritten: str
    routing: dict[str, Any]
    metadata: dict[str, Any]


@dataclass
class OrchestratorDeps:
    retriever: HybridRetriever
    reranker: BaseReranker
    query_rewriter: LegalQueryRewriter
    assembler: ContextAssembler
    client: AnthropicClientWrapper
    verifier: Any | None = None   # VerifierPipeline — optional for now
    rag_top_k: int = 10


class Orchestrator:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self._deps = deps
        self._router = QueryRouter(deps.client)
        self._specialist = RegulatorioBancarioAgent(deps.client)
        self._synthesizer = SynthesizerAgent()

    async def run(self, req: ConsultRequest) -> ConsultResponse:
        trace_id = str(uuid.uuid4())
        log = logger.bind(trace_id=trace_id)

        with tracer.start_as_current_span("orchestrator.run") as root_span:
            root_span.set_attribute("trace_id", trace_id)
            root_span.set_attribute("query_len", len(req.query))
            t_total = time.monotonic()

            # ── Route ──────────────────────────────────────────────────────
            decision: RoutingDecision = self._deps.query_rewriter  # type: ignore[assignment]  # reassigned below
            with tracer.start_as_current_span("orchestrator.route"):
                decision = self._router.route(req.query)
                log.info("routing_decision", branch=decision.branch, depth=decision.depth)

            if decision.branch == "fuera_de_alcance":
                return ConsultResponse(
                    trace_id=trace_id,
                    answer=_OUT_OF_SCOPE_ANSWER,
                    citations=[],
                    verification=None,
                    query_rewritten=req.query,
                    routing={"branch": decision.branch},
                    metadata={"latency_ms": round((time.monotonic() - t_total) * 1000)},
                )

            # ── RAG retrieve ───────────────────────────────────────────────
            with tracer.start_as_current_span("orchestrator.rag_retrieve") as rag_span:
                t_rag = time.monotonic()
                rewritten = self._deps.query_rewriter.rewrite(req.query)
                query_for_search = rewritten.expanded_query

                filters = SearchFilters(
                    jurisdiction=req.jurisdiction_hint,
                    status="vigente",
                )
                chunks = self._deps.retriever.search(query_for_search, filters)
                reranked = self._deps.reranker.rerank(
                    query_for_search, chunks, top_k=self._deps.rag_top_k
                )
                assembled = self._deps.assembler.assemble(reranked)

                rag_span.set_attribute("chunks_retrieved", len(chunks))
                rag_span.set_attribute("chunks_reranked", len(reranked))
                rag_span.set_attribute("latency_ms", round((time.monotonic() - t_rag) * 1000))

            # ── Specialist ────────────────────────────────────────────────
            with tracer.start_as_current_span("orchestrator.specialist"):
                agent_resp: AgentResponse = self._specialist.run(
                    query=rewritten.expanded_query,
                    assembled=assembled,
                    trace_id=trace_id,
                )
                agent_resp.query_rewritten = rewritten.expanded_query

            # ── Verify ────────────────────────────────────────────────────
            verification: VerificationReport | None = None
            if self._deps.verifier is not None:
                with tracer.start_as_current_span("orchestrator.verify"):
                    chunk_store = {
                        m.chunk_id: m.fragment_text for m in assembled.citation_mapping
                    }
                    verification = await self._deps.verifier.run(
                        response_id=trace_id,
                        answer_text=agent_resp.answer_text,
                        citations=assembled.citation_mapping,
                        chunk_store=chunk_store,
                    )
                    agent_resp.verification = verification

            # ── Synthesize ────────────────────────────────────────────────
            with tracer.start_as_current_span("orchestrator.synthesize"):
                final: AgentResponse = self._synthesizer.synthesize([agent_resp])

            total_ms = round((time.monotonic() - t_total) * 1000)
            root_span.set_attribute("latency_ms", total_ms)
            log.info("orchestrator_complete", latency_ms=total_ms)

            meta = final.metadata
            return ConsultResponse(
                trace_id=trace_id,
                answer=final.answer_text,
                citations=final.citations,
                verification=final.verification,
                query_rewritten=final.query_rewritten,
                routing={
                    "branch": decision.branch,
                    "jurisdictions": decision.jurisdictions,
                    "output_type": decision.output_type,
                    "depth": decision.depth,
                },
                metadata={
                    "prompt_name": meta.prompt_name,
                    "prompt_version": meta.prompt_version,
                    "prompt_hash": meta.prompt_hash[:12],
                    "model": meta.model,
                    "input_tokens": meta.input_tokens,
                    "output_tokens": meta.output_tokens,
                    "latency_ms": total_ms,
                    "cost_estimate_usd": meta.cost_estimate_usd,
                },
            )
