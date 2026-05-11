"""Failure analyzer — identifies specialist branches with degraded LDP performance."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import structlog

from lex_agents_evals_advanced.types import (
    FailedCase,
    FailedCluster,
    JudgeDimensions,
    LDPVerdict,
    LegalDataPoint,
    SingleJudgeVerdict,
)

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_LDP_UNSUPPORTED_THRESHOLD = 0.15
_CONCEPT_COVERAGE_THRESHOLD = 0.60


def _load_case_results(results_dir: Path) -> list[dict[str, Any]]:
    results_file = results_dir / "results.jsonl"
    if not results_file.exists():
        logger.warning("failure_analyzer_no_results", path=str(results_file))
        return []
    cases: list[dict[str, Any]] = []
    with results_file.open() as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _load_lemaj_verdicts(results_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Load lemaj_verdicts.jsonl → dict mapping case_id → list of LDPVerdict dicts."""
    verdicts_file = results_dir / "lemaj" / "lemaj_verdicts.jsonl"
    if not verdicts_file.exists():
        logger.warning("failure_analyzer_no_verdicts", path=str(verdicts_file))
        return {}
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with verdicts_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            # ldp_id format: "<case_id>-LDP-<n>"
            ldp_id: str = raw.get("ldp", {}).get("ldp_id", "")
            case_id = "-".join(ldp_id.split("-LDP-")[:-1]) if "-LDP-" in ldp_id else "unknown"
            by_case[case_id].append(raw)
    return dict(by_case)


def _reconstruct_ldp_verdict(raw: dict[str, Any]) -> LDPVerdict:
    ldp_raw = raw.get("ldp", {})
    ldp = LegalDataPoint(
        ldp_id=ldp_raw.get("ldp_id", ""),
        claim_text=ldp_raw.get("claim_text", ""),
        claim_type=ldp_raw.get("claim_type", "factual"),  # type: ignore[arg-type]
        supporting_refs=ldp_raw.get("supporting_refs", []),
        jurisdiction_scope=ldp_raw.get("jurisdiction_scope", "unknown"),  # type: ignore[arg-type]
        context=ldp_raw.get("context", ""),
    )
    judge_verdicts: list[SingleJudgeVerdict] = []
    for jv_raw in raw.get("judge_verdicts", []):
        dims_raw = jv_raw.get("dimensions", {})
        dims = JudgeDimensions(
            factual_support=dims_raw.get("factual_support", "partial"),  # type: ignore[arg-type]
            normative_accuracy=dims_raw.get("normative_accuracy", "partial"),  # type: ignore[arg-type]
            jurisdictional_correctness=dims_raw.get("jurisdictional_correctness", "partial"),  # type: ignore[arg-type]
            completeness_partial=dims_raw.get("completeness_partial", "partial"),  # type: ignore[arg-type]
            caveat_appropriateness=dims_raw.get("caveat_appropriateness", "partial"),  # type: ignore[arg-type]
        )
        judge_verdicts.append(SingleJudgeVerdict(
            judge_id=jv_raw.get("judge_id", "?"),
            model=jv_raw.get("model", ""),
            dimensions=dims,
            overall=jv_raw.get("overall", "partial"),  # type: ignore[arg-type]
            reasoning=jv_raw.get("reasoning", ""),
        ))
    return LDPVerdict(
        ldp=ldp,
        judge_verdicts=judge_verdicts,
        final_verdict=raw.get("final_verdict", "partial"),  # type: ignore[arg-type]
        meta_judge_used=raw.get("meta_judge_used", False),
        meta_judge_reasoning=raw.get("meta_judge_reasoning"),
    )


def _compute_ldp_unsupported_rate(ldp_verdicts: list[LDPVerdict]) -> float:
    if not ldp_verdicts:
        return 0.0
    unsupported = sum(1 for lv in ldp_verdicts if lv.final_verdict == "unsupported")
    return unsupported / len(ldp_verdicts)


def _extract_gaps(ldp_verdicts: list[LDPVerdict]) -> list[str]:
    """Collect judge reasoning from unsupported LDPs."""
    gaps: list[str] = []
    for lv in ldp_verdicts:
        if lv.final_verdict != "unsupported":
            continue
        for jv in lv.judge_verdicts:
            if jv.reasoning and len(jv.reasoning) > 10:
                gaps.append(f"[{jv.judge_id}] {jv.reasoning[:200]}")
    return gaps[:10]  # limit to 10 for prompt budget


def analyze_failures(results_dir: Path) -> list[FailedCluster]:
    """Identify failing specialist branches from a nightly eval+LeMAJ run.

    A case fails if ldp_unsupported_rate > 0.15 OR concept_coverage < 0.60.
    Results are grouped by specialist branch.
    """
    case_results = _load_case_results(results_dir)
    lemaj_verdicts = _load_lemaj_verdicts(results_dir)

    by_branch: dict[str, list[FailedCase]] = defaultdict(list)

    for cr in case_results:
        case_id: str = cr.get("case_id", "")
        branch: str = cr.get("branch_expected", "unknown")
        concept_coverage: float = float(cr.get("concept_coverage", 1.0))

        ldp_verdicts_raw = lemaj_verdicts.get(case_id, [])
        ldp_verdicts = [_reconstruct_ldp_verdict(v) for v in ldp_verdicts_raw]
        ldp_unsupported_rate = _compute_ldp_unsupported_rate(ldp_verdicts)

        is_failed = (
            ldp_unsupported_rate > _LDP_UNSUPPORTED_THRESHOLD
            or concept_coverage < _CONCEPT_COVERAGE_THRESHOLD
        )
        if not is_failed:
            continue

        unsupported_ldps = [lv for lv in ldp_verdicts if lv.final_verdict == "unsupported"]
        judge_reasoning = _extract_gaps(ldp_verdicts)

        by_branch[branch].append(FailedCase(
            case_id=case_id,
            branch=branch,
            ldp_unsupported_rate=ldp_unsupported_rate,
            concept_coverage=concept_coverage,
            unsupported_ldps=unsupported_ldps,
            judge_reasoning=judge_reasoning,
        ))

    clusters: list[FailedCluster] = []
    for branch, cases in by_branch.items():
        # Aggregate common gaps across cases
        all_gaps: list[str] = []
        for case in cases:
            all_gaps.extend(case.judge_reasoning)
        clusters.append(FailedCluster(
            branch=branch,
            failed_cases=cases,
            common_gaps=all_gaps[:15],
        ))
        logger.info(
            "failure_analyzer_cluster",
            branch=branch,
            n_failed=len(cases),
            n_gaps=len(all_gaps),
        )

    logger.info("failure_analyzer_done", n_clusters=len(clusters))
    return clusters
