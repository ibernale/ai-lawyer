"""Base agent interface and shared response types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from lex_agents_rag.assembler import AssembledContext
from lex_agents_shared.types import CitationMapping, VerificationReport


@dataclass
class AgentMetadata:
    trace_id: str
    prompt_name: str
    prompt_version: int
    prompt_hash: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_estimate_usd: float = 0.0


@dataclass
class AgentResponse:
    trace_id: str
    answer_text: str
    citations: list[CitationMapping]
    verification: VerificationReport | None
    metadata: AgentMetadata
    query_rewritten: str


@dataclass
class RoutingDecision:
    branch: str
    jurisdictions: list[str] = field(default_factory=list)
    output_type: str = "dictamen"
    depth: str = "standard"
    sub_queries: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    @abstractmethod
    def run(
        self,
        query: str,
        assembled: AssembledContext,
        trace_id: str,
    ) -> AgentResponse: ...
