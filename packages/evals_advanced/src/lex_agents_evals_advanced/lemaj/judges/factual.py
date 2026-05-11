"""JudgeA — factual-accuracy-focused judge (claude-opus-4-7, prompt vA).

JudgeA is the primary judge in the LeMAJ panel. It uses the richer vA prompt
which gives detailed instructions for grounding claims against retrieved chunks.
"""

from __future__ import annotations

from typing import ClassVar

from lex_agents_shared.anthropic_client import MODEL_OPUS

from .base import BaseJudge

__all__ = ["JudgeA"]


class JudgeA(BaseJudge):
    """Panel judge A — claude-opus-4-7, prompt variant A.

    Emphasis: factual grounding and source verification.
    Used as the first scorer in the 3-judge consensus panel.
    """

    judge_id: ClassVar[str] = "A"
    model: ClassVar[str] = MODEL_OPUS
    temperature: ClassVar[float] = 0.0
    prompt_version_key: ClassVar[str] = "A"
