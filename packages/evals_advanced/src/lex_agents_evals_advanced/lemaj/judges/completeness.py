"""CompletenessJudge — extensibility stub for a completeness-specialised judge.

This module is reserved for a future judge variant that focuses exclusively
on detecting material omissions in legal responses.  It is NOT part of the
default 3-judge panel (A / B / C) but may be enabled via panel configuration
for high-stakes queries where thoroughness is paramount.

Usage (future)::

    from lex_agents_evals_advanced.lemaj.judges.completeness import CompletenessJudge

    judge = CompletenessJudge(client)
    verdict = await judge.evaluate(ldp_id=..., ...)
"""

from __future__ import annotations

from typing import ClassVar

from lex_agents_shared.anthropic_client import MODEL_OPUS

from .base import BaseJudge

__all__ = ["CompletenessJudge"]


class CompletenessJudge(BaseJudge):
    """Optional judge specialised in completeness evaluation.

    Mirrors JudgeA (opus + vA) but is intended to be swapped in when the
    panel configuration requires an extra completeness-biased voice.

    Status: stub — not wired into the default panel.
    """

    judge_id: ClassVar[str] = "completeness"
    model: ClassVar[str] = MODEL_OPUS
    temperature: ClassVar[float] = 0.0
    prompt_version_key: ClassVar[str] = "A"
