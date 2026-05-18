"""ContractOrchestrator — coordinates contract analysis agents — Fase 13A."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

from lex_agents_agents.contracts.agents.identifier_agent import ContractIdentifierAgent
from lex_agents_agents.contracts.agents.risk_analyst_agent import RiskAnalystAgent
from lex_agents_agents.contracts.chunker import ContractChunker
from lex_agents_agents.contracts.models import (
    ContractAnalysis,
    ContractMetadata,
    ObligationGraph,
    RiskAssessment,
)

if TYPE_CHECKING:
    from lex_agents_shared.anthropic_client import AnthropicClientWrapper

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class ContractAnalysisRequest(BaseModel):
    contract_id: str
    trace_id: str
    filename: str
    content: str  # full extracted text


class ContractOrchestrator:
    """Coordinates contract analysis wave execution.

    Wave 0: ContractIdentifierAgent (sequential — metadata needed by all).
    Wave 1: RiskAnalystAgent (parallel in future; sole agent in 13A).
    Wave 2 (13B): ObligationTrackerAgent, ComplianceAgent.
    Wave 3 (13C): NegotiationAdvisorAgent.
    """

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client
        self._chunker = ContractChunker()
        self._identifier = ContractIdentifierAgent(client)
        self._risk_analyst = RiskAnalystAgent(client)

    async def run(self, req: ContractAnalysisRequest) -> ContractAnalysis:
        """Execute all analysis waves and return a fully populated ContractAnalysis."""
        start = time.monotonic()
        logger.info(
            "contract_orchestrator_start",
            contract_id=req.contract_id,
            trace_id=req.trace_id,
            filename=req.filename,
        )

        # Chunk the contract into clause-level fragments
        chunks = self._chunker.chunk(req.content, req.contract_id)
        logger.info(
            "contract_chunked",
            contract_id=req.contract_id,
            num_chunks=len(chunks),
        )

        # Wave 0: identify contract metadata (sequential — prerequisite for all waves)
        metadata: ContractMetadata = await self._identifier.identify(
            req.content, req.trace_id
        )
        logger.info(
            "contract_identified",
            contract_id=req.contract_id,
            document_type=metadata.document_type,
            parties=[p.name for p in metadata.parties],
        )

        # Wave 1: risk analysis (ObligationTracker + ComplianceAgent added in 13B)
        risk: RiskAssessment = await self._risk_analyst.analyze(
            chunks, metadata, req.trace_id
        )
        logger.info(
            "contract_risk_analyzed",
            contract_id=req.contract_id,
            overall_rating=risk.overall_rating,
            overall_score=risk.overall_score,
            num_factors=len(risk.factors),
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        analysis = ContractAnalysis(
            contract_id=req.contract_id,
            trace_id=req.trace_id,
            filename=req.filename,
            metadata=metadata,
            risk_assessment=risk,
            obligations=ObligationGraph(nodes=[], edges=[]),  # populated in 13B
            compliance_findings=[],  # populated in 13B
            summary=self._build_summary(metadata, risk),
            recommendations=self._build_recommendations(risk),
            latency_ms=latency_ms,
        )

        logger.info(
            "contract_orchestrator_complete",
            contract_id=req.contract_id,
            latency_ms=latency_ms,
        )
        return analysis

    # ------------------------------------------------------------------
    # Synthesis helpers
    # ------------------------------------------------------------------

    def _build_summary(
        self, metadata: ContractMetadata, risk: RiskAssessment
    ) -> str:
        """Build an executive summary from analysis results (≤300 words)."""
        critical = [f for f in risk.factors if f.severity == "critical"]
        high = [f for f in risk.factors if f.severity == "high"]
        party_names = " y ".join(p.name for p in metadata.parties) if metadata.parties else "partes no identificadas"
        framework_str = (
            ", ".join(metadata.applicable_framework)
            if metadata.applicable_framework
            else "no identificado"
        )
        return (
            f"Contrato de tipo {metadata.document_type} entre "
            f"{party_names}. "
            f"Jurisdicción: {', '.join(metadata.jurisdiction)}. "
            f"Ley aplicable: {metadata.governing_law}. "
            f"Marco regulatorio: {framework_str}. "
            f"Riesgo global: {risk.overall_rating.upper()} ({risk.overall_score:.2f}). "
            f"Se han identificado {len(critical)} riesgos críticos y {len(high)} altos "
            f"sobre un total de {len(risk.factors)} factores de riesgo analizados."
        )

    def _build_recommendations(self, risk: RiskAssessment) -> list[str]:
        """Extract prioritised recommendations from risk factors (top 10)."""
        by_severity: dict[str, list[str]] = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
        }
        for factor in risk.factors:
            by_severity[factor.severity].append(factor.remediation)

        result: list[str] = []
        for severity in ("critical", "high", "medium", "low"):
            result.extend(by_severity[severity])

        return result[:10]
