"""Pure metric computation functions for the eval runner.

All functions are deterministic and free of I/O — safe to unit-test in isolation.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from lex_agents_shared.types import CitationMapping, VerificationReport

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    branch_expected: str
    branch_actual: str
    routing_correct: bool
    citation_recall: float
    citation_precision: float
    hallucination_rate: float
    concept_coverage: float
    forbidden_claim_rate: float
    caveat_coverage: float
    legal_quality_score: float
    latency_ms: float
    cost_usd: float
    passed: bool  # forbidden_claim_rate == 0 and no broken_refs
    raw_response: dict[str, Any]
    error: str | None = None
    # GEval LLM-as-judge scores (Fase 11B.2) — -1.0 = not computed / failed
    geval_citation_grounding: float = -1.0
    geval_coherence: float = -1.0
    geval_completeness: float = -1.0


@dataclass
class RunSummary:
    run_id: str
    timestamp: str
    commit: str
    dataset_sha: str
    prompt_versions: dict[str, int]
    models: list[str]
    cases_total: int
    cases_passed: int
    cases_failed: int
    routing_accuracy: float
    citation_recall: float
    citation_precision: float
    hallucination_rate: float
    concept_coverage: float
    forbidden_claim_rate: float
    caveat_coverage: float
    legal_quality_score: float
    latency_p50: float
    latency_p95: float
    cost_per_query: float
    errors: list[str] = field(default_factory=list)
    # GEval averages (Fase 11B.2) — -1.0 = not computed
    geval_citation_grounding: float = -1.0
    geval_coherence: float = -1.0
    geval_completeness: float = -1.0


# ---------------------------------------------------------------------------
# Individual metric functions
# ---------------------------------------------------------------------------

def compute_citation_recall(
    citations: list[CitationMapping],
    must_cite_any_of: list[dict[str, Any]],
) -> float:
    """Fraction of expected citations that were found in the response.

    Each item in must_cite_any_of must match by CELEX/boe_id in citation source_ids.
    """
    if not must_cite_any_of:
        return 1.0

    source_ids = {c.source_id for c in citations}
    found = 0
    for item in must_cite_any_of:
        celex = item.get("celex", "")
        boe_id = item.get("boe_id", "")
        if (celex and celex in source_ids) or (boe_id and boe_id in source_ids):
            found += 1

    return found / len(must_cite_any_of)


def compute_citation_precision(report: VerificationReport) -> float:
    """Fraction of cited claims that were verified as PASSED."""
    total = max(report.claims_total, 1)
    return report.claims_passed / total


def compute_hallucination_rate(report: VerificationReport) -> float:
    """Rate of broken references and uncited claims relative to total evidence items."""
    denominator = max(report.claims_total + 1, 1)
    numerator = len(report.broken_refs) + len(report.uncited_claims)
    return numerator / denominator


def compute_concept_coverage(answer_text: str, concepts: list[str]) -> float:
    """Fraction of expected concepts (case-insensitive substring) present in answer."""
    if not concepts:
        return 1.0
    text_lower = answer_text.lower()
    found = sum(1 for c in concepts if c.lower() in text_lower)
    return found / len(concepts)


def compute_forbidden_claim_rate(answer_text: str, forbidden: list[str]) -> float:
    """Fraction of forbidden claims found in answer. Should always be 0."""
    if not forbidden:
        return 0.0
    text_lower = answer_text.lower()
    found = sum(1 for f in forbidden if f.lower() in text_lower)
    return found / len(forbidden)


def compute_caveat_coverage(answer_text: str, expected_caveats: list[str]) -> float:
    """Fraction of expected caveats mentioned in the answer."""
    if not expected_caveats:
        return 1.0
    text_lower = answer_text.lower()
    found = sum(1 for c in expected_caveats if c.lower() in text_lower)
    return found / len(expected_caveats)


def compute_legal_quality_score(cr: CaseResult, weights: dict[str, float]) -> float:
    """Weighted average of all quality dimensions."""
    score = (
        weights.get("citation_recall", 0.0) * cr.citation_recall
        + weights.get("citation_precision", 0.0) * cr.citation_precision
        + weights.get("hallucination_free", 0.0) * (1.0 - cr.hallucination_rate)
        + weights.get("concept_coverage", 0.0) * cr.concept_coverage
        + weights.get("forbidden_claim_free", 0.0) * (1.0 - cr.forbidden_claim_rate)
        + weights.get("caveat_coverage", 0.0) * cr.caveat_coverage
    )
    return round(min(max(score, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Comparative law metrics
# ---------------------------------------------------------------------------

def comparative_coverage_accuracy(
    result: dict,
    expected: dict,
) -> float:
    """Measures what fraction of expected coverage gaps were correctly declared
    in the comparative output.

    = declared_gaps_matching_expected / total_expected_gaps

    A gap 'matches' if:
    - result.comparative_output.coverage_gaps contains an entry for the expected jurisdiction
    - AND the entry's coverage level matches expected_coverage (partial/insufficient)

    Returns 1.0 if no gaps expected and none declared.
    Returns 0.0 if gaps expected but comparative_output is None.
    """
    expected_gaps = expected.get("must_flag_coverage_gap", [])
    if not expected_gaps:
        return 1.0

    comparative = result.get("comparative_output")
    if not comparative:
        return 0.0

    declared_gaps = comparative.get("coverage_gaps", [])
    declared_jurisdictions = {g["jurisdiction"] for g in declared_gaps}

    # Also check dimensions for partial/insufficient coverage cells
    dimensions = comparative.get("dimensions", [])
    partial_in_dimensions: set[str] = set()
    for dim in dimensions:
        for jur, entry in dim.get("by_jurisdiction", {}).items():
            if entry.get("coverage") in ("partial", "insufficient"):
                partial_in_dimensions.add(jur)

    all_declared = declared_jurisdictions | partial_in_dimensions

    matched = sum(
        1 for gap in expected_gaps
        if gap["jurisdiction"] in all_declared
    )
    return matched / len(expected_gaps)


def must_compare_jurisdictions_check(result: dict, expected: dict) -> bool:
    """Returns True if all expected jurisdictions appear in comparative_output."""
    expected_jurs = set(expected.get("must_compare_jurisdictions", []))
    if not expected_jurs:
        return True
    comparative = result.get("comparative_output")
    if not comparative:
        return False
    actual_jurs = set(comparative.get("jurisdictions_compared", []))
    return expected_jurs.issubset(actual_jurs)


def must_identify_divergences_check(result: dict, expected: dict) -> bool:
    """Returns True if all expected divergences are identified (by dimension name)."""
    expected_divs = expected.get("must_identify_divergences", [])
    if not expected_divs:
        return True
    comparative = result.get("comparative_output")
    if not comparative:
        return False
    actual_dims = {d["dimension"] for d in comparative.get("divergences", [])}
    for exp_div in expected_divs:
        if not any(exp_div["dimension"].lower() in actual_dim.lower() for actual_dim in actual_dims):
            return False
    return True


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_summary(
    results: list[CaseResult],
    weights: dict[str, float],
    meta: dict[str, Any],
) -> RunSummary:
    """Aggregate per-case results into a RunSummary with p50/p95 latency."""
    total = len(results)
    passed = sum(1 for r in results if r.passed and r.error is None)
    failed = total - passed

    def _avg(values: list[float]) -> float:
        return statistics.mean(values) if values else 0.0

    def _percentile(values: list[float], p: int) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        # Nearest-rank method: rank = ceil(p/100 * n), index = rank - 1
        rank = max(1, math.ceil(len(sorted_vals) * p / 100))
        return sorted_vals[min(rank - 1, len(sorted_vals) - 1)]

    ok_results = [r for r in results if r.error is None]
    latencies = [r.latency_ms for r in ok_results]
    costs = [r.cost_usd for r in ok_results]

    routing_correct = sum(1 for r in results if r.routing_correct)

    # Re-compute legal_quality_score after aggregation (use stored values)
    lqs_values = [r.legal_quality_score for r in ok_results]

    def _geval_avg(values: list[float]) -> float:
        """Average only valid scores (>= 0); return -1.0 if none."""
        valid = [v for v in values if v >= 0.0]
        return _avg(valid) if valid else -1.0

    return RunSummary(
        run_id=meta.get("run_id", ""),
        timestamp=meta.get("timestamp", ""),
        commit=meta.get("commit", ""),
        dataset_sha=meta.get("dataset_sha", ""),
        prompt_versions=meta.get("prompt_versions", {}),
        models=meta.get("models", []),
        cases_total=total,
        cases_passed=passed,
        cases_failed=failed,
        routing_accuracy=routing_correct / max(total, 1),
        citation_recall=_avg([r.citation_recall for r in ok_results]),
        citation_precision=_avg([r.citation_precision for r in ok_results]),
        hallucination_rate=_avg([r.hallucination_rate for r in ok_results]),
        concept_coverage=_avg([r.concept_coverage for r in ok_results]),
        forbidden_claim_rate=_avg([r.forbidden_claim_rate for r in ok_results]),
        caveat_coverage=_avg([r.caveat_coverage for r in ok_results]),
        legal_quality_score=_avg(lqs_values),
        latency_p50=_percentile(latencies, 50),
        latency_p95=_percentile(latencies, 95),
        cost_per_query=_avg(costs),
        errors=[r.error for r in results if r.error is not None],
        geval_citation_grounding=_geval_avg([r.geval_citation_grounding for r in ok_results]),
        geval_coherence=_geval_avg([r.geval_coherence for r in ok_results]),
        geval_completeness=_geval_avg([r.geval_completeness for r in ok_results]),
    )
