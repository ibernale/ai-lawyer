"""CaveatJudge — extensibility stub for a caveat-appropriateness-specialised judge.

This module is reserved for a future judge variant that focuses exclusively
on whether legal responses include the appropriate disclaimers, uncertainty
hedges, and regulatory caveats required for banking compliance contexts.

Usage (future)::

    from lex_agents_evals_advanced.lemaj.judges.caveat import CaveatJudge

    judge = CaveatJudge(client)
    verdict = await judge.evaluate(ldp_id=..., ...)
"""

from __future__ import annotations

from typing import ClassVar

from lex_agents_shared.anthropic_client import MODEL_OPUS

from .base import BaseJudge

__all__ = ["CaveatJudge"]


class CaveatJudge(BaseJudge):
    """Optional judge specialised in caveat and disclaimer evaluation.

    Uses prompt vB (few-shot variant) to better calibrate nuanced caveats
    around pending transpositions, national vs. EU norms, and ambiguous
    regulatory perimeters.

    Status: stub — not wired into the default panel.
    """

    judge_id: ClassVar[str] = "caveat"
    model: ClassVar[str] = MODEL_OPUS
    temperature: ClassVar[float] = 0.0
    prompt_version_key: ClassVar[str] = "B"
