"""ContractOrchestrator — coordinates contract analysis agents — Fase 13A/13B/13C."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

from lex_agents_agents.contracts.agents.clause_optimizer_agent import ClauseOptimizerAgent
from lex_agents_agents.contracts.agents.compliance_agent import ComplianceAgent
from lex_agents_agents.contracts.agents.identifier_agent import ContractIdentifierAgent
from lex_agents_agents.contracts.agents.negotiation_advisor_agent import NegotiationAdvisorAgent
from lex_agents_agents.contracts.agents.obligation_tracker_agent import ObligationTrackerAgent
from lex_agents_agents.contracts.agents.risk_analyst_agent import RiskAnalystAgent
from lex_agents_agents.contracts.chunker import ContractChunker
from lex_agents_agents.contracts.models import (
    ClauseAlternatives,
    ComplianceFinding,
    ContractAnalysis,
    ContractMetadata,
    NegotiationSummary,
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


class SseEvent(BaseModel):
    event: str
    data: dict  # type: ignore[type-arg]


class ContractOrchestrator:
    """Coordinates contract analysis wave execution.

    Wave 0: ContractIdentifierAgent (sequential — metadata needed by all).
    Wave 1: RiskAnalystAgent + ObligationTrackerAgent + ComplianceAgent (parallel).
    Wave 2 (13C): NegotiationAdvisorAgent → ClauseOptimizerAgent (sequential).
    ContractSynthesizerAgent (always last).
    """

    def __init__(self, client: AnthropicClientWrapper) -> None:
        self._client = client
        self._chunker = ContractChunker()
        self._identifier = ContractIdentifierAgent(client)
        self._risk_analyst = RiskAnalystAgent(client)
        self._obligation_tracker = ObligationTrackerAgent(client)
        self._compliance_agent = ComplianceAgent(client)
        self._negotiation_advisor = NegotiationAdvisorAgent(client)
        self._clause_optimizer = ClauseOptimizerAgent(client)

    async def run(self, req: ContractAnalysisRequest) -> ContractAnalysis:
        """Execute all analysis waves and return a fully populated ContractAnalysis."""
        start = time.monotonic()
        logger.info(
            "contract_orchestrator_start",
            contract_id=req.contract_id,
            trace_id=req.trace_id,
            filename=req.filename,
        )

        chunks = self._chunker.chunk(req.content, req.contract_id)
        logger.info("contract_chunked", contract_id=req.contract_id, num_chunks=len(chunks))

        # Wave 0: identify (sequential — prerequisite)
        metadata: ContractMetadata = await self._identifier.identify(
            req.content, req.trace_id
        )
        logger.info(
            "contract_identified",
            contract_id=req.contract_id,
            document_type=metadata.document_type,
        )

        # Wave 1: parallel execution
        risk, obligations, compliance_findings = await asyncio.gather(
            self._risk_analyst.analyze(chunks, metadata, req.trace_id),
            self._obligation_tracker.extract(chunks, metadata, req.trace_id),
            self._compliance_agent.check(chunks, metadata, req.trace_id),
        )
        logger.info(
            "contract_wave1_complete",
            contract_id=req.contract_id,
            risk_rating=risk.overall_rating,
            num_obligations=len(obligations.nodes),
            num_compliance_findings=len(compliance_findings),
        )

        # Wave 2: negotiation (sequential — uses Wave 1 outputs as context)
        negotiation: NegotiationSummary = await self._negotiation_advisor.advise(
            chunks, metadata, risk, req.trace_id
        )
        clause_alternatives: list[ClauseAlternatives] = await self._clause_optimizer.optimize(
            chunks, negotiation.priority_issues, metadata, req.trace_id
        )
        logger.info(
            "contract_wave2_complete",
            contract_id=req.contract_id,
            posture_label=negotiation.posture_label,
            num_priority_issues=len(negotiation.priority_issues),
            num_clause_alternatives=len(clause_alternatives),
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        analysis = ContractAnalysis(
            contract_id=req.contract_id,
            trace_id=req.trace_id,
            filename=req.filename,
            metadata=metadata,
            risk_assessment=risk,
            obligations=obligations,
            compliance_findings=compliance_findings,
            negotiation=negotiation,
            clause_alternatives=clause_alternatives,
            summary=self._build_summary(metadata, risk, obligations, compliance_findings),
            recommendations=self._build_recommendations(risk, compliance_findings),
            latency_ms=latency_ms,
        )

        logger.info(
            "contract_orchestrator_complete",
            contract_id=req.contract_id,
            latency_ms=latency_ms,
        )
        return analysis

    async def run_streaming(
        self, req: ContractAnalysisRequest
    ) -> AsyncGenerator[SseEvent, None]:
        """Execute analysis and yield SSE events at each pipeline stage.

        Event types:
        - progress: {"step": str, "message": str, "pct": int}
        - result:   {"analysis": <ContractAnalysis JSON>}
        - done:     {}
        - error:    {"message": str, "trace_id": str}
        """
        start = time.monotonic()

        # ── Chunking ────────────────────────────────────────────────────────
        yield SseEvent(
            event="progress",
            data={"step": "chunking", "message": "Procesando documento…", "pct": 5},
        )
        try:
            chunks = self._chunker.chunk(req.content, req.contract_id)
        except Exception as exc:
            logger.exception("contract_stream_chunking_error", contract_id=req.contract_id)
            yield SseEvent(
                event="error",
                data={"message": f"Error al procesar el documento: {exc}", "trace_id": req.trace_id},
            )
            return

        yield SseEvent(
            event="progress",
            data={
                "step": "chunking",
                "message": f"{len(chunks)} cláusulas identificadas",
                "pct": 10,
            },
        )

        # ── Wave 0: Identification ───────────────────────────────────────────
        yield SseEvent(
            event="progress",
            data={"step": "identification", "message": "Identificando tipo y partes del contrato…", "pct": 20},
        )
        try:
            metadata = await self._identifier.identify(req.content, req.trace_id)
        except Exception as exc:
            logger.exception("contract_stream_identification_error", contract_id=req.contract_id)
            yield SseEvent(
                event="error",
                data={"message": f"Error en identificación: {exc}", "trace_id": req.trace_id},
            )
            return

        yield SseEvent(
            event="progress",
            data={
                "step": "identification",
                "message": (
                    f"Contrato: {metadata.document_type} · "
                    f"{', '.join(p.name for p in metadata.parties[:2])}"
                ),
                "pct": 30,
            },
        )

        # ── Wave 1: Parallel analysis ────────────────────────────────────────
        yield SseEvent(
            event="progress",
            data={
                "step": "analysis",
                "message": "Analizando riesgos, obligaciones y compliance en paralelo…",
                "pct": 40,
            },
        )

        try:
            risk_task = asyncio.create_task(
                self._risk_analyst.analyze(chunks, metadata, req.trace_id)
            )
            obligation_task = asyncio.create_task(
                self._obligation_tracker.extract(chunks, metadata, req.trace_id)
            )
            compliance_task = asyncio.create_task(
                self._compliance_agent.check(chunks, metadata, req.trace_id)
            )

            # Emit incremental progress as each agent completes
            done_count = 0
            for coro in asyncio.as_completed([risk_task, obligation_task, compliance_task]):
                await coro
                done_count += 1
                pct = 40 + done_count * 14  # 54, 68, 82
                yield SseEvent(
                    event="progress",
                    data={
                        "step": "analysis",
                        "message": f"Análisis {done_count}/3 completado…",
                        "pct": pct,
                    },
                )

            risk: RiskAssessment = risk_task.result()
            obligations: ObligationGraph = obligation_task.result()
            compliance_findings = compliance_task.result()

        except Exception as exc:
            logger.exception("contract_stream_wave1_error", contract_id=req.contract_id)
            yield SseEvent(
                event="error",
                data={"message": f"Error en análisis: {exc}", "trace_id": req.trace_id},
            )
            return

        # ── Wave 2: Negotiation ─────────────────────────────────────────────
        yield SseEvent(
            event="progress",
            data={"step": "negotiation", "message": "Evaluando posición negociadora…", "pct": 88},
        )

        try:
            negotiation: NegotiationSummary = await self._negotiation_advisor.advise(
                chunks, metadata, risk, req.trace_id
            )
            clause_alternatives: list[ClauseAlternatives] = await self._clause_optimizer.optimize(
                chunks, negotiation.priority_issues, metadata, req.trace_id
            )
        except Exception as exc:
            logger.exception("contract_stream_wave2_error", contract_id=req.contract_id)
            yield SseEvent(
                event="error",
                data={"message": f"Error en análisis de negociación: {exc}", "trace_id": req.trace_id},
            )
            return

        yield SseEvent(
            event="progress",
            data={
                "step": "negotiation",
                "message": f"Postura: {negotiation.posture_label}",
                "pct": 93,
            },
        )

        # ── Synthesis ────────────────────────────────────────────────────────
        yield SseEvent(
            event="progress",
            data={"step": "synthesis", "message": "Sintetizando resultados…", "pct": 96},
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        analysis = ContractAnalysis(
            contract_id=req.contract_id,
            trace_id=req.trace_id,
            filename=req.filename,
            metadata=metadata,
            risk_assessment=risk,
            obligations=obligations,
            compliance_findings=compliance_findings,
            negotiation=negotiation,
            clause_alternatives=clause_alternatives,
            summary=self._build_summary(metadata, risk, obligations, compliance_findings),
            recommendations=self._build_recommendations(risk, compliance_findings),
            latency_ms=latency_ms,
        )

        logger.info(
            "contract_stream_complete",
            contract_id=req.contract_id,
            latency_ms=latency_ms,
            risk_rating=risk.overall_rating,
        )

        yield SseEvent(event="result", data=json.loads(analysis.model_dump_json()))
        yield SseEvent(event="done", data={})

    # ------------------------------------------------------------------
    # Synthesis helpers
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        metadata: ContractMetadata,
        risk: RiskAssessment,
        obligations: ObligationGraph | None = None,
        compliance_findings: list[ComplianceFinding] | None = None,
    ) -> str:
        """Build an executive summary from analysis results (≤300 words)."""
        critical = [f for f in risk.factors if f.severity == "critical"]
        high = [f for f in risk.factors if f.severity == "high"]
        party_names = " y ".join(p.name for p in metadata.parties) if metadata.parties else "partes no identificadas"
        framework_str = (
            ", ".join(metadata.applicable_framework) if metadata.applicable_framework else "no identificado"
        )

        summary = (
            f"Contrato de tipo {metadata.document_type} entre "
            f"{party_names}. "
            f"Jurisdicción: {', '.join(metadata.jurisdiction)}. "
            f"Ley aplicable: {metadata.governing_law}. "
            f"Marco regulatorio: {framework_str}. "
            f"Riesgo global: {risk.overall_rating.upper()} ({risk.overall_score:.2f}). "
            f"Se han identificado {len(critical)} riesgos críticos y {len(high)} altos "
            f"sobre un total de {len(risk.factors)} factores de riesgo."
        )

        if obligations and obligations.nodes:
            obl_count = sum(1 for n in obligations.nodes if n.deontic_type == "obligation")
            prh_count = sum(1 for n in obligations.nodes if n.deontic_type == "prohibition")
            summary += (
                f" Obligaciones identificadas: {len(obligations.nodes)} normas deónticas "
                f"({obl_count} obligaciones, {prh_count} prohibiciones)."
            )

        if compliance_findings:
            non_compliant = sum(1 for f in compliance_findings if f.status == "non_compliant")
            requires_review = sum(1 for f in compliance_findings if f.status == "requires_review")
            if non_compliant or requires_review:
                summary += (
                    f" Compliance: {non_compliant} incumplimientos y "
                    f"{requires_review} áreas que requieren revisión."
                )

        return summary

    def _build_recommendations(
        self,
        risk: RiskAssessment,
        compliance_findings: list[ComplianceFinding] | None = None,
    ) -> list[str]:
        """Extract prioritised recommendations (top 10) combining risk + compliance."""
        by_severity: dict[str, list[str]] = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
        }
        for factor in risk.factors:
            by_severity[factor.severity].append(factor.remediation)

        # Prepend non_compliant compliance findings
        compliance_recs: list[str] = []
        if compliance_findings:
            for finding in compliance_findings:
                if finding.status == "non_compliant" and finding.recommendation:
                    compliance_recs.append(
                        f"[{finding.regulation}] {finding.recommendation}"
                    )

        result: list[str] = compliance_recs.copy()
        for severity in ("critical", "high", "medium", "low"):
            result.extend(by_severity[severity])

        return result[:10]
