"""JudgeB — normative-accuracy-focused judge (claude-opus-4-7, prompt vB).

JudgeB uses an alternative prompt (vB) that includes two few-shot examples
of LDP evaluations, providing a different reasoning perspective from JudgeA
while maintaining the same model capacity.
"""

from __future__ import annotations

from typing import ClassVar

from lex_agents_shared.anthropic_client import MODEL_OPUS

from .base import BaseJudge

__all__ = ["JudgeB"]


class JudgeB(BaseJudge):
    """Panel judge B — claude-opus-4-7, prompt variant B.

    Emphasis: normative interpretation and legal accuracy.
    Uses prompt vB (few-shot variant) for richer calibration.
    Used as the second scorer in the 3-judge consensus panel.
    """

    judge_id: ClassVar[str] = "B"
    model: ClassVar[str] = MODEL_OPUS
    temperature: ClassVar[float] = 0.0
    prompt_version_key: ClassVar[str] = "B"
