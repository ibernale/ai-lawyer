"""Pydantic v2 models for contract analysis — Fase 13A."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ContractParty(BaseModel):
    name: str
    role: Literal[
        "lender",
        "borrower",
        "buyer",
        "seller",
        "provider",
        "client",
        "controller",
        "processor",
        "employer",
        "employee",
        "disclosing",
        "receiving",
    ]
    legal_entity_type: str | None = None  # SA | SL | foundation | individual | ...


class ContractMetadata(BaseModel):
    document_type: Literal[
        "NDA",
        "MSA",
        "SLA",
        "LoanAgreement",
        "CreditFacility",
        "EmploymentContract",
        "DataProcessingAgreement",
        "ServiceAgreement",
        "Guarantee",
        "ISDA",
        "Other",
    ]
    parties: list[ContractParty]
    effective_date: str | None = None  # ISO8601 or natural language
    termination_date: str | None = None
    jurisdiction: list[str]  # e.g. ["ES", "EU"]
    governing_law: str
    applicable_framework: list[str]  # e.g. ["GDPR", "CRR", "CódigoCivil", "AML", ...]
    contract_language: str = "es"


class RiskFactor(BaseModel):
    category: Literal["financial", "legal", "operational", "strategic"]
    issue: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float  # 0.0-1.0
    clause_refs: list[str]  # e.g. ["[CLAUSE:3]", "[CLAUSE:7]"]
    remediation: str


class RiskAssessment(BaseModel):
    overall_score: float  # 0.0-1.0
    overall_rating: Literal["green", "yellow", "red", "critical"]
    factors: list[RiskFactor]


class Obligation(BaseModel):
    id: str
    party: str
    deontic_type: Literal["obligation", "permission", "prohibition", "right"]
    description: str
    conditions: str | None = None
    deadline: str | None = None
    exceptions: list[str] = []
    clause_ref: str


class ObligationEdge(BaseModel):
    from_id: str
    to_id: str
    relationship: Literal["depends_on", "conflicts_with", "reinforces"]


class ObligationGraph(BaseModel):
    nodes: list[Obligation]
    edges: list[ObligationEdge]


class ComplianceFinding(BaseModel):
    regulation: str  # e.g. "GDPR Art. 28", "CRR Art. 92"
    status: Literal["compliant", "non_compliant", "requires_review", "not_applicable"]
    finding: str
    clause_refs: list[str]
    recommendation: str | None = None


class ContractAnalysis(BaseModel):
    contract_id: str
    trace_id: str
    filename: str
    metadata: ContractMetadata
    risk_assessment: RiskAssessment
    obligations: ObligationGraph
    compliance_findings: list[ComplianceFinding]
    # negotiation fields — populated in Fase 13C, optional here
    negotiation: list[dict] = []  # type: ignore[type-arg]
    clause_alternatives: list[dict] = []  # type: ignore[type-arg]
    # synthesis
    summary: str  # executive summary ≤300 words
    recommendations: list[str]  # prioritised action items
    # audit metadata
    analysis_trace: dict = {}  # type: ignore[type-arg]
    latency_ms: int | None = None
    cost_estimate_usd: float | None = None
