"""Shared types for LeMAJ evaluation and reflection-driven prompt evolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Legal Data Point — atomic verifiable claim extracted from an agent response
# ---------------------------------------------------------------------------

@dataclass
class LegalDataPoint:
    ldp_id: str
    """Unique identifier: '<case_id>-LDP-<n>'."""
    claim_text: str
    """Single verifiable legal claim."""
    claim_type: Literal["factual", "interpretive", "procedural", "cautionary"]
    supporting_refs: list[str]
    """[REF:n] references found in claim_text or context."""
    jurisdiction_scope: Literal["ES", "EU", "ES+EU", "global", "unknown"]
    context: str
    """Parent paragraph from the original response."""


# ---------------------------------------------------------------------------
# Judge verdict types
# ---------------------------------------------------------------------------

@dataclass
class JudgeDimensions:
    factual_support: Literal["supported", "partial", "unsupported"]
    normative_accuracy: Literal["supported", "partial", "unsupported"]
    jurisdictional_correctness: Literal["supported", "partial", "unsupported"]
    completeness_partial: Literal["supported", "partial", "unsupported"]
    caveat_appropriateness: Literal["supported", "partial", "unsupported"]


@dataclass
class SingleJudgeVerdict:
    judge_id: str
    """'A' | 'B' | 'C'"""
    model: str
    dimensions: JudgeDimensions
    overall: Literal["supported", "partial", "unsupported"]
    reasoning: str


@dataclass
class LDPVerdict:
    ldp: LegalDataPoint
    judge_verdicts: list[SingleJudgeVerdict]
    """Always length 3 (one per panel judge)."""
    final_verdict: Literal["supported", "partial", "unsupported", "review_required"]
    meta_judge_used: bool
    meta_judge_reasoning: str | None


# ---------------------------------------------------------------------------
# LeMAJ run-level aggregate metrics
# ---------------------------------------------------------------------------

@dataclass
class LeMAJRunMetrics:
    run_id: str
    timestamp: str
    cases_evaluated: int
    total_ldps: int
    ldp_supported_rate: float
    ldp_unsupported_rate: float
    ldp_partial_rate: float
    ldp_review_required_rate: float
    # Cohen's Kappa per dimension per judge pair
    kappa_ab: dict[str, float] = field(default_factory=dict)
    kappa_ac: dict[str, float] = field(default_factory=dict)
    kappa_bc: dict[str, float] = field(default_factory=dict)
    # Fleiss' Kappa per dimension (all 3 judges)
    fleiss_kappa: dict[str, float] = field(default_factory=dict)
    coverage_mean: float = 0.0
    cost_usd: float = 0.0
    low_kappa_dimensions: list[str] = field(default_factory=list)
    """Dimensions where Fleiss Kappa < 0.6 — flag for panel prompt review."""


# ---------------------------------------------------------------------------
# Reflection types
# ---------------------------------------------------------------------------

@dataclass
class FailedCase:
    case_id: str
    branch: str
    ldp_unsupported_rate: float
    concept_coverage: float
    unsupported_ldps: list[LDPVerdict]
    judge_reasoning: list[str]


@dataclass
class FailedCluster:
    branch: str
    """Specialist branch responsible (e.g. 'regulatorio_bancario_ue_es')."""
    failed_cases: list[FailedCase]
    common_gaps: list[str]
    """Recurrent gaps across cases identified by failure analyzer."""


@dataclass
class PromptDiff:
    branch: str
    current_version: int
    current_prompt_path: str
    diff_text: str
    """Unified diff format: --- a/... +++ b/..."""
    rationale: str
    adr_compliant: bool
    """False if proposed change contradicts any ADR."""


@dataclass
class RegressionCase:
    case_id: str
    query: str
    concept_coverage_before: float
    concept_coverage_after: float
    forbidden_claim_rate_after: float
    passed: bool


@dataclass
class RegressionResult:
    diff: PromptDiff
    accepted: bool
    regression_cases: list[RegressionCase]
    notes: str


@dataclass
class PromptEvolutionPR:
    branch_name: str
    """git branch: prompt-evolution/<timestamp>-<specialist>"""
    pr_url: str
    pr_number: int
    specialist: str
    new_version: int
    diff_summary: str
