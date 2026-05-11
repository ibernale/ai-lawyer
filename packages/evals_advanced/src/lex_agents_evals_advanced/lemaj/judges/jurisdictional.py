"""JudgeC — jurisdictional-correctness-focused judge (claude-haiku-4-5, prompt vA).

JudgeC provides a fast, cost-efficient third opinion using Haiku with the same
vA system prompt as JudgeA.  Its lower cost allows the panel to afford a third
independent score without significantly increasing latency.
"""

from __future__ import annotations

from typing import ClassVar

from lex_agents_shared.anthropic_client import MODEL_HAIKU

from .base import BaseJudge

__all__ = ["JudgeC"]


class JudgeC(BaseJudge):
    """Panel judge C — claude-haiku-4-5, prompt variant A.

    Emphasis: jurisdictional scope and cross-border norm application.
    Reuses prompt vA for consistency with JudgeA; smaller model trades
    raw capability for speed and cost efficiency.
    Used as the tiebreaker / third scorer in the 3-judge consensus panel.
    """

    judge_id: ClassVar[str] = "C"
    model: ClassVar[str] = MODEL_HAIKU
    temperature: ClassVar[float] = 0.0
    prompt_version_key: ClassVar[str] = "A"
