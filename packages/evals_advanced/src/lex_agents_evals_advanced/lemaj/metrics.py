"""LeMAJ metrics — LDP rates, Cohen's Kappa, Fleiss' Kappa, coverage.

All functions are pure (no I/O, no LLM calls) and deterministic.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from sklearn.metrics import cohen_kappa_score  # type: ignore[import-untyped]

from lex_agents_evals_advanced.types import (
    LDPVerdict,
    LegalDataPoint,
    LeMAJRunMetrics,
)

_DIMENSIONS = [
    "factual_support",
    "normative_accuracy",
    "jurisdictional_correctness",
    "completeness_partial",
    "caveat_appropriateness",
]
_KAPPA_LOW_THRESHOLD = 0.6
_VERDICTS = ["supported", "partial", "unsupported"]


def _dim_verdicts_for_judge(
    verdicts: list[LDPVerdict], judge_id: str, dimension: str
) -> list[str]:
    """Extract per-LDP verdict for one judge and one dimension."""
    out: list[str] = []
    for lv in verdicts:
        sv = next((j for j in lv.judge_verdicts if j.judge_id == judge_id), None)
        if sv is None:
            out.append("partial")  # treat missing as partial (neutral)
        else:
            out.append(getattr(sv.dimensions, dimension, "partial"))
    return out


def cohen_kappa_pair(
    verdicts_j1: list[str], verdicts_j2: list[str], labels: list[str] | None = None
) -> float:
    """Compute Cohen's Kappa between two judge verdict sequences.

    Returns NaN if there is insufficient data (< 2 unique labels).
    """
    if len(verdicts_j1) < 2 or len(verdicts_j2) < 2:
        return float("nan")
    unique = set(verdicts_j1) | set(verdicts_j2)
    if len(unique) < 2:
        # All labels identical → Kappa is undefined (or 1.0 by convention)
        return 1.0 if verdicts_j1 == verdicts_j2 else float("nan")
    try:
        return float(cohen_kappa_score(verdicts_j1, verdicts_j2, labels=labels or _VERDICTS))
    except Exception:
        return float("nan")


def fleiss_kappa_all(verdicts_matrix: list[list[str]]) -> float:
    """Compute Fleiss' Kappa for ≥2 raters over categorical data.

    Args:
        verdicts_matrix: shape [n_raters][n_items], each entry is a category string.

    Returns:
        Fleiss' Kappa as float. NaN if insufficient data.
    """
    if not verdicts_matrix or not verdicts_matrix[0]:
        return float("nan")
    n_raters = len(verdicts_matrix)
    n_items = len(verdicts_matrix[0])
    if n_items < 2:
        return float("nan")

    categories = sorted({v for row in verdicts_matrix for v in row})
    if len(categories) < 2:
        return 1.0

    k = len(categories)
    cat_idx = {c: i for i, c in enumerate(categories)}

    # Build rating matrix [n_items][k]: count of raters assigning each category
    rating = np.zeros((n_items, k), dtype=float)
    for rater_verdicts in verdicts_matrix:
        for item_i, verdict in enumerate(rater_verdicts):
            ci = cat_idx.get(verdict, 0)
            rating[item_i, ci] += 1

    # Proportion of all assignments to each category
    p_j = rating.sum(axis=0) / (n_items * n_raters)

    # Per-subject agreement P_i
    P_i = (
        ((rating * (rating - 1)).sum(axis=1))
        / (n_raters * (n_raters - 1))
    )
    P_bar = P_i.mean()
    P_e_bar = float(np.sum(p_j ** 2))

    if P_e_bar >= 1.0:
        return 1.0
    return float((P_bar - P_e_bar) / (1.0 - P_e_bar))


def compute_kappa_by_dimension(
    verdicts: list[LDPVerdict],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    """Compute Cohen's Kappa for pairs (A-B, A-C, B-C) and Fleiss' Kappa for all 3.

    Returns (kappa_ab, kappa_ac, kappa_bc, fleiss_kappa) each mapping dim → float.
    """
    kappa_ab: dict[str, float] = {}
    kappa_ac: dict[str, float] = {}
    kappa_bc: dict[str, float] = {}
    fleiss: dict[str, float] = {}

    for dim in _DIMENSIONS:
        a = _dim_verdicts_for_judge(verdicts, "A", dim)
        b = _dim_verdicts_for_judge(verdicts, "B", dim)
        c = _dim_verdicts_for_judge(verdicts, "C", dim)

        kappa_ab[dim] = cohen_kappa_pair(a, b)
        kappa_ac[dim] = cohen_kappa_pair(a, c)
        kappa_bc[dim] = cohen_kappa_pair(b, c)
        fleiss[dim] = fleiss_kappa_all([a, b, c])

    return kappa_ab, kappa_ac, kappa_bc, fleiss


def compute_ldp_rates(verdicts: list[LDPVerdict]) -> dict[str, float]:
    """Return ldp_supported_rate, ldp_partial_rate, ldp_unsupported_rate, ldp_review_required_rate."""
    if not verdicts:
        return {
            "supported": 0.0,
            "partial": 0.0,
            "unsupported": 0.0,
            "review_required": 0.0,
        }
    counts: Counter[str] = Counter(lv.final_verdict for lv in verdicts)
    total = len(verdicts)
    return {
        "supported": counts["supported"] / total,
        "partial": counts["partial"] / total,
        "unsupported": counts["unsupported"] / total,
        "review_required": counts["review_required"] / total,
    }


def compute_coverage(
    produced_ldps: list[LegalDataPoint],
    expected_concepts: list[str],
) -> float:
    """Compute % of expected concepts that appear (substring) in any produced claim_text."""
    if not expected_concepts:
        return 1.0
    all_claims = " ".join(ldp.claim_text.lower() for ldp in produced_ldps)
    matched = sum(1 for concept in expected_concepts if concept.lower() in all_claims)
    return matched / len(expected_concepts)


def build_lemaj_metrics(
    verdicts_per_case: dict[str, list[LDPVerdict]],
    run_id: str,
    cost_usd: float,
    coverage_per_case: dict[str, float] | None = None,
) -> LeMAJRunMetrics:
    """Aggregate per-case LDP verdicts into LeMAJRunMetrics."""
    all_verdicts: list[LDPVerdict] = []
    for case_verdicts in verdicts_per_case.values():
        all_verdicts.extend(case_verdicts)

    rates = compute_ldp_rates(all_verdicts)

    kappa_ab: dict[str, float] = {}
    kappa_ac: dict[str, float] = {}
    kappa_bc: dict[str, float] = {}
    fleiss_kappa: dict[str, float] = {}
    low_kappa_dims: list[str] = []

    if all_verdicts:
        kappa_ab, kappa_ac, kappa_bc, fleiss_kappa = compute_kappa_by_dimension(all_verdicts)
        low_kappa_dims = [
            dim for dim, k in fleiss_kappa.items()
            if not math.isnan(k) and k < _KAPPA_LOW_THRESHOLD
        ]

    coverage_mean = 0.0
    if coverage_per_case:
        vals = list(coverage_per_case.values())
        coverage_mean = sum(vals) / len(vals) if vals else 0.0

    return LeMAJRunMetrics(
        run_id=run_id,
        timestamp=datetime.now(UTC).isoformat(),
        cases_evaluated=len(verdicts_per_case),
        total_ldps=len(all_verdicts),
        ldp_supported_rate=rates["supported"],
        ldp_unsupported_rate=rates["unsupported"],
        ldp_partial_rate=rates["partial"],
        ldp_review_required_rate=rates["review_required"],
        kappa_ab=kappa_ab,
        kappa_ac=kappa_ac,
        kappa_bc=kappa_bc,
        fleiss_kappa=fleiss_kappa,
        coverage_mean=coverage_mean,
        cost_usd=cost_usd,
        low_kappa_dimensions=low_kappa_dims,
    )


def render_report(metrics: LeMAJRunMetrics, human_review_ldps: list[LDPVerdict]) -> str:
    """Render a Markdown summary report for `lemaj_report.md`."""
    lines = [
        f"# LeMAJ Report — {metrics.run_id}",
        f"**Generated:** {metrics.timestamp}",
        "",
        "## Summary",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Cases evaluated | {metrics.cases_evaluated} |",
        f"| Total LDPs | {metrics.total_ldps} |",
        f"| LDP supported rate | {metrics.ldp_supported_rate:.1%} |",
        f"| LDP partial rate | {metrics.ldp_partial_rate:.1%} |",
        f"| LDP unsupported rate | {metrics.ldp_unsupported_rate:.1%} |",
        f"| LDP review required | {metrics.ldp_review_required_rate:.1%} |",
        f"| Coverage (mean) | {metrics.coverage_mean:.1%} |",
        f"| Cost (USD) | ${metrics.cost_usd:.4f} |",
        "",
        "## Inter-Judge Agreement (Fleiss' Kappa)",
        "| Dimension | Fleiss κ | Low? |",
        "|-----------|---------|------|",
    ]
    for dim in _DIMENSIONS:
        k = metrics.fleiss_kappa.get(dim, float("nan"))
        flag = "⚠️" if dim in metrics.low_kappa_dimensions else "✅"
        k_str = f"{k:.3f}" if not math.isnan(k) else "N/A"
        lines.append(f"| {dim} | {k_str} | {flag} |")

    if metrics.low_kappa_dimensions:
        lines += [
            "",
            "### ⚠️ Dimensions requiring panel prompt review",
            "Fleiss Kappa < 0.6 indicates task definition issues in the judge prompt, "
            "not judge inconsistency.",
        ]
        for dim in metrics.low_kappa_dimensions:
            lines.append(f"- `{dim}`")

    if human_review_ldps:
        lines += [
            "",
            f"## Human Review Required ({len(human_review_ldps)} LDPs)",
            "These LDPs were excluded from automatic metrics.",
            "",
            "| LDP ID | Claim (first 120 chars) |",
            "|--------|------------------------|",
        ]
        for lv in human_review_ldps[:50]:
            lines.append(f"| {lv.ldp.ldp_id} | {lv.ldp.claim_text[:120]} |")
        if len(human_review_ldps) > 50:
            lines.append(f"| … | {len(human_review_ldps) - 50} more — see lemaj_verdicts.jsonl |")

    return "\n".join(lines)
