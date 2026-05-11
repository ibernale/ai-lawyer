"""Unit tests for evals/runners/metrics.py — pure functions, no I/O."""

from __future__ import annotations

import pytest
from lex_agents_shared.types import CitationMapping, VerificationReport

from evals.runners.metrics import (
    CaseResult,
    aggregate_summary,
    compute_citation_precision,
    compute_citation_recall,
    compute_concept_coverage,
    compute_forbidden_claim_rate,
    compute_hallucination_rate,
    compute_legal_quality_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mapping(source_id: str, index: int = 1) -> CitationMapping:
    return CitationMapping(
        index=index,
        chunk_id=f"chunk-{index}",
        source_id=source_id,
        hierarchy_path="CRR > art. 92",
        fragment_text="texto de ejemplo",
    )


def _report(
    total: int = 5,
    passed: int = 5,
    failed: int = 0,
    uncertain: int = 0,
    broken_refs: list[int] | None = None,
    uncited_claims: list[str] | None = None,
) -> VerificationReport:
    return VerificationReport(
        response_id="test",
        claims_total=total,
        claims_passed=passed,
        claims_failed=failed,
        claims_uncertain=uncertain,
        broken_refs=broken_refs or [],
        uncited_claims=uncited_claims or [],
    )


def _case_result(**overrides: object) -> CaseResult:
    defaults: dict = {
        "case_id": "TEST-001",
        "branch_expected": "regulatorio_bancario_ue_es",
        "branch_actual": "regulatorio_bancario_ue_es",
        "routing_correct": True,
        "citation_recall": 1.0,
        "citation_precision": 1.0,
        "hallucination_rate": 0.0,
        "concept_coverage": 1.0,
        "forbidden_claim_rate": 0.0,
        "caveat_coverage": 1.0,
        "legal_quality_score": 0.0,
        "latency_ms": 500.0,
        "cost_usd": 0.01,
        "passed": True,
        "raw_response": {},
        "error": None,
    }
    defaults.update(overrides)
    return CaseResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# citation_recall
# ---------------------------------------------------------------------------

class TestCitationRecall:
    def test_full_match(self) -> None:
        citations = [_mapping("32013R0575"), _mapping("32014L0059", index=2)]
        must_cite = [
            {"type": "regulation", "celex": "32013R0575", "articles": ["92"]},
            {"type": "directive", "celex": "32014L0059", "articles": ["10"]},
        ]
        assert compute_citation_recall(citations, must_cite) == 1.0

    def test_partial_match(self) -> None:
        citations = [_mapping("32013R0575")]
        must_cite = [
            {"type": "regulation", "celex": "32013R0575", "articles": ["92"]},
            {"type": "directive", "celex": "32014L0059", "articles": ["10"]},
        ]
        assert compute_citation_recall(citations, must_cite) == pytest.approx(0.5)

    def test_no_match(self) -> None:
        citations = [_mapping("UNKNOWN")]
        must_cite = [{"type": "regulation", "celex": "32013R0575", "articles": ["92"]}]
        assert compute_citation_recall(citations, must_cite) == 0.0

    def test_empty_expected(self) -> None:
        assert compute_citation_recall([], []) == 1.0

    def test_boe_id_match(self) -> None:
        citations = [_mapping("BOE-A-2014-12345")]
        must_cite = [{"type": "royal_decree", "boe_id": "BOE-A-2014-12345"}]
        assert compute_citation_recall(citations, must_cite) == 1.0


# ---------------------------------------------------------------------------
# citation_precision
# ---------------------------------------------------------------------------

class TestCitationPrecision:
    def test_all_passed(self) -> None:
        report = _report(total=10, passed=10)
        assert compute_citation_precision(report) == 1.0

    def test_partial(self) -> None:
        report = _report(total=10, passed=7)
        assert compute_citation_precision(report) == pytest.approx(0.7)

    def test_zero_total_avoids_division_error(self) -> None:
        report = _report(total=0, passed=0)
        assert compute_citation_precision(report) == 0.0


# ---------------------------------------------------------------------------
# hallucination_rate
# ---------------------------------------------------------------------------

class TestHallucinationRate:
    def test_clean_report(self) -> None:
        report = _report(total=5, broken_refs=[], uncited_claims=[])
        assert compute_hallucination_rate(report) == 0.0

    def test_broken_refs_increase_rate(self) -> None:
        report = _report(total=5, broken_refs=[1, 2])
        rate = compute_hallucination_rate(report)
        assert rate > 0

    def test_uncited_claims_increase_rate(self) -> None:
        report = _report(total=5, uncited_claims=["claim A", "claim B"])
        rate = compute_hallucination_rate(report)
        assert rate > 0

    def test_denominator_never_zero(self) -> None:
        report = _report(total=0)
        assert compute_hallucination_rate(report) == 0.0


# ---------------------------------------------------------------------------
# concept_coverage
# ---------------------------------------------------------------------------

class TestConceptCoverage:
    def test_all_present(self) -> None:
        text = "El ratio CET1 y los fondos propios son requisitos clave."
        concepts = ["ratio CET1", "fondos propios"]
        assert compute_concept_coverage(text, concepts) == 1.0

    def test_partial(self) -> None:
        text = "El ratio CET1 es importante."
        concepts = ["ratio CET1", "fondos propios"]
        assert compute_concept_coverage(text, concepts) == pytest.approx(0.5)

    def test_empty_concepts_returns_one(self) -> None:
        assert compute_concept_coverage("any text", []) == 1.0

    def test_case_insensitive(self) -> None:
        text = "El RATIO CET1 se aplica."
        concepts = ["ratio cet1"]
        assert compute_concept_coverage(text, concepts) == 1.0


# ---------------------------------------------------------------------------
# forbidden_claim_rate
# ---------------------------------------------------------------------------

class TestForbiddenClaimDetected:
    def test_forbidden_found(self) -> None:
        text = "Basilea IV está plenamente en vigor desde enero."
        forbidden = ["Basilea IV está plenamente en vigor"]
        assert compute_forbidden_claim_rate(text, forbidden) == 1.0

    def test_no_forbidden(self) -> None:
        text = "El CRR establece requisitos de capital."
        forbidden = ["Basilea IV está plenamente en vigor"]
        assert compute_forbidden_claim_rate(text, forbidden) == 0.0

    def test_empty_forbidden(self) -> None:
        assert compute_forbidden_claim_rate("any text", []) == 0.0


# ---------------------------------------------------------------------------
# legal_quality_score formula
# ---------------------------------------------------------------------------

class TestLegalQualityScore:
    _WEIGHTS = {
        "citation_recall": 0.35,
        "citation_precision": 0.25,
        "hallucination_free": 0.20,
        "concept_coverage": 0.10,
        "forbidden_claim_free": 0.05,
        "caveat_coverage": 0.05,
    }

    def test_perfect_case(self) -> None:
        cr = _case_result(
            citation_recall=1.0, citation_precision=1.0, hallucination_rate=0.0,
            concept_coverage=1.0, forbidden_claim_rate=0.0, caveat_coverage=1.0,
        )
        score = compute_legal_quality_score(cr, self._WEIGHTS)
        assert score == pytest.approx(1.0)

    def test_zero_case(self) -> None:
        cr = _case_result(
            citation_recall=0.0, citation_precision=0.0, hallucination_rate=1.0,
            concept_coverage=0.0, forbidden_claim_rate=1.0, caveat_coverage=0.0,
        )
        score = compute_legal_quality_score(cr, self._WEIGHTS)
        assert score == pytest.approx(0.0)

    def test_partial_weights(self) -> None:
        cr = _case_result(
            citation_recall=0.8, citation_precision=0.8, hallucination_rate=0.0,
            concept_coverage=0.5, forbidden_claim_rate=0.0, caveat_coverage=0.5,
        )
        expected = (
            0.35 * 0.8 + 0.25 * 0.8 + 0.20 * 1.0
            + 0.10 * 0.5 + 0.05 * 1.0 + 0.05 * 0.5
        )
        score = compute_legal_quality_score(cr, self._WEIGHTS)
        assert score == pytest.approx(round(expected, 4))


# ---------------------------------------------------------------------------
# aggregate_summary latency percentiles
# ---------------------------------------------------------------------------

class TestAggregateLatencyPercentiles:
    _WEIGHTS = {
        "citation_recall": 0.35,
        "citation_precision": 0.25,
        "hallucination_free": 0.20,
        "concept_coverage": 0.10,
        "forbidden_claim_free": 0.05,
        "caveat_coverage": 0.05,
    }

    def test_p50_and_p95(self) -> None:
        latencies = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        results = [_case_result(latency_ms=float(l)) for l in latencies]
        summary = aggregate_summary(results, self._WEIGHTS, {"run_id": "x", "timestamp": "", "commit": "", "dataset_sha": "", "prompt_versions": {}, "models": []})
        assert summary.latency_p50 == pytest.approx(500.0)
        assert summary.latency_p95 == pytest.approx(1000.0)

    def test_empty_results(self) -> None:
        summary = aggregate_summary([], self._WEIGHTS, {"run_id": "x", "timestamp": "", "commit": "", "dataset_sha": "", "prompt_versions": {}, "models": []})
        assert summary.cases_total == 0
        assert summary.latency_p50 == 0.0
