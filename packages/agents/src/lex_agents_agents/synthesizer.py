"""Synthesizer agent — MVP pass-through for single specialist."""

from __future__ import annotations

import structlog

from .base_agent import AgentResponse
from .prompt_loader import load_prompt

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class SynthesizerAgent:
    """MVP: returns the single specialist response unchanged.

    Loads sintesis/v1 prompt for version tracking even though it makes no LLM call.
    Future multi-specialist version will merge list[AgentResponse] here.
    """

    def __init__(self, prompt_version: int = 1) -> None:
        self._cfg = load_prompt("sintesis", version=prompt_version)

    def synthesize(self, responses: list[AgentResponse]) -> AgentResponse:
        if not responses:
            raise ValueError("SynthesizerAgent.synthesize called with empty response list")
        if len(responses) == 1:
            return responses[0]
        # Multi-specialist placeholder — not yet implemented
        logger.warning("synthesizer_multi_specialist_not_implemented", n=len(responses))
        return responses[0]
