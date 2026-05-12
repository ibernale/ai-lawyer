"""Comparative law synthesizer — produces ComparativeResponse (ADR 0027)."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from lex_agents_shared.anthropic_client import MODEL_OPUS, AnthropicClientWrapper
from lex_agents_shared.types import (
    CitationMapping,
    ComparativeDimension,
    ComparativeResponse,
    CoverageGap,
    Divergence,
    JurisdictionEntry,
)
from opentelemetry import trace

from lex_agents_agents.base_agent import AgentResponse
from lex_agents_agents.prompt_loader import load_prompt
from lex_agents_agents.shared.definition_of_done import PlannerOutput

logger: structlog.BoundLogger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# Suggested dimensions used when Planner provides none.
_DEFAULT_DIMENSIONS = [
    "Marco regulatorio general",
    "Requisitos de autorización",
    "Obligaciones de información",
    "Protección del cliente/usuario",
    "Régimen sancionador",
    "Supervisión y autoridad competente",
]

# Known partial-coverage jurisdictions (sources in AMBER state).
_PARTIAL_JURISDICTIONS = {"BR", "MX"}
_PARTIAL_REASONS: dict[str, str] = {
    "BR": "Fuentes INLABS-DOU en estado AMBER — cobertura LGPD parcial",
    "MX": "Fuentes SIDOF-DOF en estado AMBER — cobertura regulatoria parcial",
    "UK": "Cobertura post-Brexit parcial (legislation.gov.uk + FCA)",
}
_PARTIAL_RECOMMENDATIONS: dict[str, str] = {
    "BR": "Consultar asesoría local especializada en LGPD y regulación BCB/CMN",
    "MX": "Consultar asesoría local especializada en CNBV, Banxico y SHCP",
    "UK": "Verificar con asesoría local el impacto del retained EU law post-Brexit",
}


class ComparativeSynthesizer:
    """Converts parallel Maker responses into a structured ComparativeResponse.

    Activated exclusively when output_type == "analisis_comparativo" and
    len(responses) >= 2 (ADR 0027).
    """

    def __init__(
        self,
        client: AnthropicClientWrapper,
        prompt_version: int = 1,
    ) -> None:
        self._client = client
        try:
            self._cfg = load_prompt("sintesis_comparative", version=prompt_version)
        except FileNotFoundError:
            # Fallback to sintesis/v2 if comparative prompt not yet deployed.
            logger.warning(
                "comparative_synthesizer.prompt_not_found",
                version=prompt_version,
                fallback="sintesis/v2",
            )
            self._cfg = load_prompt("sintesis", version=2)

    async def synthesize(
        self,
        responses: list[AgentResponse],
        planner_output: PlannerOutput,
        trace_id: str,
    ) -> ComparativeResponse:
        """Produce a ComparativeResponse from parallel Maker outputs."""
        jurisdictions = planner_output.jurisdictions or []

        with tracer.start_as_current_span("comparative_synthesizer.synthesize") as span:
            span.set_attribute("n_responses", len(responses))
            span.set_attribute("jurisdictions", ",".join(jurisdictions))

            user_content = self._build_user_prompt(responses, planner_output)

            t0 = time.monotonic()
            raw_json: str | None = None
            in_tok = out_tok = 0

            try:
                resp = self._client.messages_create(
                    model=MODEL_OPUS,
                    max_tokens=self._cfg.max_tokens,
                    system=self._cfg.body,
                    messages=[{"role": "user", "content": user_content}],
                )
                raw_json = resp.content[0].text  # type: ignore[union-attr]
                in_tok = resp.usage.input_tokens
                out_tok = resp.usage.output_tokens
            except Exception:
                logger.exception("comparative_synthesizer.api_error", trace_id=trace_id)

            latency = (time.monotonic() - t0) * 1000
            span.set_attribute("latency_ms", round(latency))

            logger.info(
                "comparative_synthesizer.done",
                trace_id=trace_id,
                latency_ms=round(latency),
                in_tok=in_tok,
                out_tok=out_tok,
            )

            if raw_json:
                parsed = self._parse_response(raw_json, trace_id, jurisdictions)
            else:
                parsed = self._fallback_response(responses, planner_output, trace_id)

            # Ensure all partial jurisdictions have explicit CoverageGaps.
            parsed = self._ensure_coverage_gaps(parsed, jurisdictions)

            return parsed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        responses: list[AgentResponse],
        planner_output: PlannerOutput,
    ) -> str:
        parts: list[str] = []

        jurisdictions = planner_output.jurisdictions or []
        parts.append(f"JURISDICCIONES A COMPARAR: {', '.join(jurisdictions)}\n")

        # Dimensions from DoD or default list.
        dod = planner_output.definition_of_done
        dimensions = getattr(dod, "suggested_dimensions", None) or _DEFAULT_DIMENSIONS
        parts.append("DIMENSIONES SUGERIDAS:\n")
        for dim in dimensions:
            parts.append(f"- {dim}\n")
        parts.append("\n")

        # Specialist responses, labelled by jurisdiction.
        parts.append("# Respuestas de los especialistas por jurisdicción\n")
        branch_names = [t.branch for t in planner_output.sub_tasks]
        for resp, branch in zip(responses, branch_names, strict=False):
            # Derive jurisdiction from branch name or planner output.
            jur = self._jurisdiction_for_branch(branch, planner_output)
            parts.append(f"\n[JURISDICCIÓN: {jur}] [RAMA: {branch}]\n\n{resp.answer_text}\n")

        return "".join(parts)

    @staticmethod
    def _jurisdiction_for_branch(branch: str, planner_output: PlannerOutput) -> str:
        """Best-effort mapping of branch name to jurisdiction code."""
        mapping = {
            "regulatorio_bancario_ue_es": "ES/EU",
            "datos_personales_rgpd": "EU",
            "laboral": "ES",
            "mercantil_societario": "ES",
            "penal_economico": "ES",
            "administrativo": "ES",
        }
        return mapping.get(branch, branch.upper()[:2])

    def _parse_response(
        self,
        raw: str,
        trace_id: str,
        jurisdictions: list[str],
    ) -> ComparativeResponse:
        """Parse LLM JSON output into ComparativeResponse; fallback on error."""
        # Strip accidental code fences.
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "comparative_synthesizer.json_parse_error",
                trace_id=trace_id,
                error=str(exc),
            )
            return self._error_response(trace_id, jurisdictions, f"JSON parse error: {exc}")

        try:
            dimensions = [
                ComparativeDimension(
                    name=d["name"],
                    by_jurisdiction={
                        jur: JurisdictionEntry(**entry)
                        for jur, entry in d.get("by_jurisdiction", {}).items()
                    },
                )
                for d in data.get("dimensions", [])
            ]
            divergences = [Divergence(**dv) for dv in data.get("divergences", [])]
            coverage_gaps = [CoverageGap(**g) for g in data.get("coverage_gaps", [])]
            citations = [
                CitationMapping(**c) for c in data.get("citations", [])
            ]

            return ComparativeResponse(
                trace_id=trace_id,
                issue=data.get("issue", ""),
                jurisdictions_compared=data.get("jurisdictions_compared", jurisdictions),
                dimensions=dimensions,
                divergences=divergences,
                common_ground=data.get("common_ground", []),
                risk_differential=data.get("risk_differential", {}),
                risk_rationale=data.get("risk_rationale", ""),
                coverage_gaps=coverage_gaps,
                citations=citations,
                verification_status="amber",
            )
        except Exception as exc:
            logger.warning(
                "comparative_synthesizer.pydantic_error",
                trace_id=trace_id,
                error=str(exc),
            )
            return self._error_response(trace_id, jurisdictions, f"Schema validation error: {exc}")

    def _fallback_response(
        self,
        responses: list[AgentResponse],
        planner_output: PlannerOutput,
        trace_id: str,
    ) -> ComparativeResponse:
        """Minimal valid ComparativeResponse when LLM call fails."""
        jurisdictions = planner_output.jurisdictions or []
        dimensions = [
            ComparativeDimension(
                name="Análisis por jurisdicción",
                by_jurisdiction={
                    self._jurisdiction_for_branch(t.branch, planner_output): JurisdictionEntry(
                        text=resp.answer_text[:500] if resp.answer_text else None,
                        refs=[c.index for c in resp.citations[:3]],
                        coverage="partial",
                        note="Síntesis comparativa no disponible — ver respuesta individual",
                    )
                    for t, resp in zip(planner_output.sub_tasks, responses, strict=False)
                },
            )
        ]
        return ComparativeResponse(
            trace_id=trace_id,
            issue="Análisis comparativo (síntesis automática no disponible)",
            jurisdictions_compared=jurisdictions,
            dimensions=dimensions,
            risk_differential=dict.fromkeys(jurisdictions, "medium"),
            risk_rationale=(
                "Síntesis automática no disponible — se muestran respuestas individuales. "
                "Este análisis comparativo es un borrador asistido por IA y requiere "
                "validación por juristas especializados en cada jurisdicción."
            ),
            coverage_gaps=[
                CoverageGap(
                    jurisdiction=j,
                    reason="Síntesis comparativa no disponible",
                    recommendation="Revisar análisis individual por rama",
                )
                for j in jurisdictions
            ],
            verification_status="amber",
        )

    @staticmethod
    def _error_response(
        trace_id: str,
        jurisdictions: list[str],
        error_detail: str,
    ) -> ComparativeResponse:
        return ComparativeResponse(
            trace_id=trace_id,
            issue="Error en síntesis comparativa",
            jurisdictions_compared=jurisdictions or ["unknown"],
            coverage_gaps=[
                CoverageGap(
                    jurisdiction=j,
                    reason=f"Error de síntesis: {error_detail}",
                    recommendation="Reintentar consulta o escalar a equipo técnico",
                )
                for j in (jurisdictions or ["unknown"])
            ],
            risk_differential=dict.fromkeys(jurisdictions or ["unknown"], "medium"),
            risk_rationale=(
                f"No fue posible completar la síntesis comparativa ({error_detail}). "
                "Este análisis comparativo es un borrador asistido por IA y requiere "
                "validación por juristas especializados en cada jurisdicción."
            ),
            verification_status="red",
        )

    @staticmethod
    def _ensure_coverage_gaps(
        result: ComparativeResponse,
        jurisdictions: list[str],
    ) -> ComparativeResponse:
        """Add CoverageGap entries for known partial-coverage jurisdictions if missing."""
        declared = {g.jurisdiction for g in result.coverage_gaps}
        extra: list[CoverageGap] = []
        for jur in jurisdictions:
            if jur in _PARTIAL_JURISDICTIONS and jur not in declared:
                extra.append(
                    CoverageGap(
                        jurisdiction=jur,
                        reason=_PARTIAL_REASONS.get(jur, "Cobertura parcial"),
                        recommendation=_PARTIAL_RECOMMENDATIONS.get(
                            jur, "Consultar asesoría local"
                        ),
                    )
                )
        if extra:
            result = result.model_copy(
                update={"coverage_gaps": result.coverage_gaps + extra}
            )
        return result
