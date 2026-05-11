"""JudgePanel — runs 3 LDP judges in parallel and resolves disagreements.

Consensus rule: if all three judges agree on `overall`, that verdict is used
directly (meta_judge_used=False). Any disagreement triggers MetaJudge
arbitration.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import TYPE_CHECKING

import structlog

from lex_agents_shared.anthropic_client import AnthropicClientWrapper

from lex_agents_evals_advanced.types import (
    JudgeDimensions,
    LDPVerdict,
    LegalDataPoint,
    SingleJudgeVerdict,
)
from lex_agents_evals_advanced.lemaj.judges.base import BaseJudge
from lex_agents_evals_advanced.lemaj.judges.factual import JudgeA
from lex_agents_evals_advanced.lemaj.judges.normative import JudgeB
from lex_agents_evals_advanced.lemaj.judges.jurisdictional import JudgeC

if TYPE_CHECKING:
    from lex_agents_evals_advanced.lemaj.meta_judge import MetaJudge

logger: structlog.BoundLogger = structlog.get_logger(__name__)


def _convert_verdict(
    v: "lex_agents_evals_advanced.lemaj.judges.base.SingleJudgeVerdict",  # type: ignore[name-defined]
) -> SingleJudgeVerdict:
    """Convert base.py SingleJudgeVerdict to types.py SingleJudgeVerdict."""
    dims = JudgeDimensions(
        factual_support=v.dimensions.factual_support,  # type: ignore[arg-type]
        normative_accuracy=v.dimensions.normative_accuracy,  # type: ignore[arg-type]
        jurisdictional_correctness=v.dimensions.jurisdictional_correctness,  # type: ignore[arg-type]
        completeness_partial=v.dimensions.completeness_partial,  # type: ignore[arg-type]
        caveat_appropriateness=v.dimensions.caveat_appropriateness,  # type: ignore[arg-type]
    )
    return SingleJudgeVerdict(
        judge_id=v.judge_id,
        model=v.model,
        dimensions=dims,
        overall=v.overall,  # type: ignore[arg-type]
        reasoning=v.reasoning,
    )


class JudgePanel:
    """Orchestrates 3 LDP judges and resolves disagreements via MetaJudge."""

    def __init__(
        self,
        client: AnthropicClientWrapper,
        judges: list[type[BaseJudge]] | None = None,
    ) -> None:
        judge_classes = judges or [JudgeA, JudgeB, JudgeC]
        self._judges: list[BaseJudge] = [cls(client) for cls in judge_classes]
        self._meta_judge: MetaJudge | None = None
        self._client = client

    def _get_meta_judge(self) -> "MetaJudge":
        if self._meta_judge is None:
            from lex_agents_evals_advanced.lemaj.meta_judge import MetaJudge
            self._meta_judge = MetaJudge(self._client)
        return self._meta_judge

    async def evaluate_ldp(
        self,
        ldp: LegalDataPoint,
        context_chunks: str,
    ) -> LDPVerdict:
        """Evaluate a single LDP with all judges in parallel.

        Consensus (all 3 agree on overall) → use that verdict directly.
        Any disagreement → MetaJudge arbitrates.
        """
        judge_tasks = [
            judge.evaluate(
                ldp_id=ldp.ldp_id,
                claim_text=ldp.claim_text,
                claim_type=ldp.claim_type,
                supporting_refs=ldp.supporting_refs,
                jurisdiction_scope=ldp.jurisdiction_scope,
                context=ldp.context,
                context_chunks=context_chunks,
            )
            for judge in self._judges
        ]

        raw_results = await asyncio.gather(*judge_tasks, return_exceptions=True)

        base_verdicts = []
        for i, result in enumerate(raw_results):
            if isinstance(result, BaseException):
                judge_id = self._judges[i].judge_id
                logger.warning(
                    "panel_judge_exception",
                    judge_id=judge_id,
                    ldp_id=ldp.ldp_id,
                    error=str(result),
                )
            else:
                base_verdicts.append(result)

        if not base_verdicts:
            logger.error("panel_all_judges_failed", ldp_id=ldp.ldp_id)
            return LDPVerdict(
                ldp=ldp,
                judge_verdicts=[],
                final_verdict="review_required",
                meta_judge_used=False,
                meta_judge_reasoning="All judges failed — requires human review.",
            )

        converted = [_convert_verdict(v) for v in base_verdicts]

        # Consensus check
        overall_counts: Counter[str] = Counter(v.overall for v in converted)
        majority = overall_counts.most_common(1)[0][0]
        all_agree = len(overall_counts) == 1

        if all_agree or len(base_verdicts) < len(self._judges):
            # All agree, or we only got partial results — use majority/only verdict
            final_verdict = majority
            meta_judge_used = False
            meta_judge_reasoning = None
            logger.info(
                "panel_consensus",
                ldp_id=ldp.ldp_id,
                verdict=final_verdict,
                n_judges=len(converted),
            )
        else:
            # Disagreement — arbitrate with MetaJudge
            meta = self._get_meta_judge()
            final_verdict, meta_judge_reasoning = await meta.arbitrate(ldp, converted)
            meta_judge_used = True
            logger.info(
                "panel_meta_judge_arbitration",
                ldp_id=ldp.ldp_id,
                verdict=final_verdict,
            )

        return LDPVerdict(
            ldp=ldp,
            judge_verdicts=converted,
            final_verdict=final_verdict,  # type: ignore[arg-type]
            meta_judge_used=meta_judge_used,
            meta_judge_reasoning=meta_judge_reasoning,
        )

    async def evaluate_all(
        self,
        ldps: list[LegalDataPoint],
        context_chunks: str,
    ) -> list[LDPVerdict]:
        """Evaluate all LDPs sequentially to avoid rate limits."""
        verdicts: list[LDPVerdict] = []
        for ldp in ldps:
            verdict = await self.evaluate_ldp(ldp, context_chunks)
            verdicts.append(verdict)
        return verdicts
