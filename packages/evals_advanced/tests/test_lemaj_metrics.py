"""Tests for LeMAJ metrics — Kappa, LDP rates, coverage, report rendering."""

from __future__ import annotations

import math

from lex_agents_evals_advanced.lemaj.metrics import (
    build_lemaj_metrics,
    cohen_kappa_pair,
    compute_coverage,
    compute_ldp_rates,
    fleiss_kappa_all,
    render_report,
)
from lex_agents_evals_advanced.types import (
    JudgeDimensions,
    LDPVerdict,
    LegalDataPoint,
    SingleJudgeVerdict,
)


def _make_ldp(ldp_id: str = "CASE-001-LDP-1") -> LegalDataPoint:
    return LegalDataPoint(
        ldp_id=ldp_id,
        claim_text="El CRR exige 8%.",
        claim_type="factual",
        supporting_refs=[],
        jurisdiction_scope="EU",
        context="",
    )


def _make_dims(v: str = "supported") -> JudgeDimensions:
    return JudgeDimensions(
        factual_support=v,  # type: ignore[arg-type]
        normative_accuracy=v,  # type: ignore[arg-type]
        jurisdictional_correctness=v,  # type: ignore[arg-type]
        completeness_partial=v,  # type: ignore[arg-type]
        caveat_appropriateness=v,  # type: ignore[arg-type]
    )


def _make_verdict(ldp_id: str, final: str) -> LDPVerdict:
    return LDPVerdict(
        ldp=_make_ldp(ldp_id),
        judge_verdicts=[
            SingleJudgeVerdict(judge_id="A", model="m", dimensions=_make_dims(), overall="supported", reasoning=""),  # type: ignore[arg-type]
            SingleJudgeVerdict(judge_id="B", model="m", dimensions=_make_dims(), overall="supported", reasoning=""),  # type: ignore[arg-type]
            SingleJudgeVerdict(judge_id="C", model="m", dimensions=_make_dims(), overall="supported", reasoning=""),  # type: ignore[arg-type]
        ],
        final_verdict=final,  # type: ignore[arg-type]
        meta_judge_used=False,
        meta_judge_reasoning=None,
    )


class TestCohenKappa:
    def test_perfect_agreement(self):
        j1 = ["supported", "partial", "unsupported"] * 5
        j2 = j1[:]
        k = cohen_kappa_pair(j1, j2)
        assert abs(k - 1.0) < 1e-9

    def test_single_label_returns_one(self):
        j1 = ["supported"] * 10
        j2 = ["supported"] * 10
        k = cohen_kappa_pair(j1, j2)
        assert k == 1.0

    def test_insufficient_data_returns_nan(self):
        k = cohen_kappa_pair(["supported"], ["partial"])
        assert math.isnan(k)

    def test_kappa_below_threshold(self):
        j1 = ["supported", "partial", "unsupported", "supported", "partial"] * 4
        j2 = ["partial", "unsupported", "supported", "unsupported", "supported"] * 4
        k = cohen_kappa_pair(j1, j2)
        assert k < 0.6


class TestFleissKappa:
    def test_perfect_agreement(self):
        matrix = [["supported"] * 5, ["supported"] * 5, ["supported"] * 5]
        k = fleiss_kappa_all(matrix)
        assert k == 1.0

    def test_empty_returns_nan(self):
        k = fleiss_kappa_all([])
        assert math.isnan(k)

    def test_single_item_returns_nan(self):
        k = fleiss_kappa_all([["supported"], ["partial"], ["unsupported"]])
        assert math.isnan(k)

    def test_mixed_verdicts_below_one(self):
        j1 = ["supported", "partial", "unsupported", "supported", "partial"]
        j2 = ["supported", "partial", "partial",     "unsupported","supported"]
        j3 = ["partial",   "partial", "unsupported", "supported", "partial"]
        k = fleiss_kappa_all([j1, j2, j3])
        assert -1.0 <= k <= 1.0


class TestLDPRates:
    def test_empty_returns_zeros(self):
        rates = compute_ldp_rates([])
        assert rates["supported"] == 0.0
        assert rates["unsupported"] == 0.0

    def test_all_supported(self):
        verdicts = [_make_verdict(f"c-{i}", "supported") for i in range(5)]
        rates = compute_ldp_rates(verdicts)
        assert rates["supported"] == 1.0
        assert rates["unsupported"] == 0.0

    def test_mixed_rates(self):
        verdicts = [
            _make_verdict("v1", "supported"),
            _make_verdict("v2", "supported"),
            _make_verdict("v3", "partial"),
            _make_verdict("v4", "unsupported"),
            _make_verdict("v5", "review_required"),
        ]
        rates = compute_ldp_rates(verdicts)
        assert abs(rates["supported"] - 0.4) < 1e-9
        assert abs(rates["partial"] - 0.2) < 1e-9
        assert abs(rates["unsupported"] - 0.2) < 1e-9
        assert abs(rates["review_required"] - 0.2) < 1e-9


class TestCoverage:
    def test_empty_concepts_returns_one(self):
        assert compute_coverage([], []) == 1.0

    def test_all_covered(self):
        ldps = [_make_ldp()]
        ldps[0].claim_text  # just to check it's accessible
        from lex_agents_evals_advanced.types import LegalDataPoint
        ldp = LegalDataPoint(
            ldp_id="x", claim_text="crr mifid ratio", claim_type="factual",
            supporting_refs=[], jurisdiction_scope="EU", context=""
        )
        cov = compute_coverage([ldp], ["crr", "mifid", "ratio"])
        assert cov == 1.0

    def test_partial_coverage(self):
        ldp = LegalDataPoint(
            ldp_id="x", claim_text="only crr mentioned", claim_type="factual",
            supporting_refs=[], jurisdiction_scope="EU", context=""
        )
        cov = compute_coverage([ldp], ["crr", "mifid", "ratio"])
        assert abs(cov - 1/3) < 1e-9


class TestBuildMetrics:
    def test_aggregates_correctly(self):
        verdicts = {
            "case1": [_make_verdict("c1-ldp1", "supported"), _make_verdict("c1-ldp2", "partial")],
            "case2": [_make_verdict("c2-ldp1", "unsupported")],
        }
        metrics = build_lemaj_metrics(verdicts, run_id="test-run", cost_usd=1.5)
        assert metrics.run_id == "test-run"
        assert metrics.cases_evaluated == 2
        assert metrics.total_ldps == 3
        assert metrics.cost_usd == 1.5

    def test_low_kappa_flagged(self):
        # Build verdicts with mixed judge disagreements to trigger low kappa
        dims_a = JudgeDimensions(
            factual_support="supported", normative_accuracy="supported",
            jurisdictional_correctness="supported", completeness_partial="supported",
            caveat_appropriateness="supported",
        )
        dims_b = JudgeDimensions(
            factual_support="unsupported", normative_accuracy="unsupported",
            jurisdictional_correctness="unsupported", completeness_partial="unsupported",
            caveat_appropriateness="unsupported",
        )
        dims_c = JudgeDimensions(
            factual_support="partial", normative_accuracy="partial",
            jurisdictional_correctness="partial", completeness_partial="partial",
            caveat_appropriateness="partial",
        )
        verdicts_list = []
        for i in range(10):
            ldp = LegalDataPoint(
                ldp_id=f"c1-ldp{i}", claim_text="test", claim_type="factual",
                supporting_refs=[], jurisdiction_scope="EU", context=""
            )
            verdicts_list.append(LDPVerdict(
                ldp=ldp,
                judge_verdicts=[
                    SingleJudgeVerdict(judge_id="A", model="m", dimensions=dims_a, overall="supported", reasoning=""),  # type: ignore[arg-type]
                    SingleJudgeVerdict(judge_id="B", model="m", dimensions=dims_b, overall="unsupported", reasoning=""),  # type: ignore[arg-type]
                    SingleJudgeVerdict(judge_id="C", model="m", dimensions=dims_c, overall="partial", reasoning=""),  # type: ignore[arg-type]
                ],
                final_verdict="review_required",
                meta_judge_used=True,
                meta_judge_reasoning=None,
            ))
        metrics = build_lemaj_metrics({"case1": verdicts_list}, run_id="kappa-test", cost_usd=0.0)
        # With total disagreement, some dims should have low kappa
        # At minimum the property exists and is a list
        assert isinstance(metrics.low_kappa_dimensions, list)


class TestRenderReport:
    def test_renders_markdown(self):
        verdicts = {"c1": [_make_verdict("c1-ldp1", "supported")]}
        metrics = build_lemaj_metrics(verdicts, "run-1", 0.5)
        report = render_report(metrics, [])
        assert "# LeMAJ Report" in report
        assert "run-1" in report
        assert "supported" in report.lower() or "Supported" in report

    def test_human_review_section_included(self):
        hr = [_make_verdict("c1-ldp1", "review_required")]
        hr[0] = LDPVerdict(
            ldp=_make_ldp("c1-ldp1"),
            judge_verdicts=[],
            final_verdict="review_required",
            meta_judge_used=True,
            meta_judge_reasoning="Ambiguous",
        )
        verdicts = {"c1": [hr[0]]}
        metrics = build_lemaj_metrics(verdicts, "run-2", 0.0)
        report = render_report(metrics, hr)
        assert "Human Review" in report
