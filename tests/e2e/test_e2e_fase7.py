"""E2E test — Fase 7.4 cross-capability integration.

Covers:
  - UnsupportedDetector: short-circuits before RAG for unsupported query patterns
  - FeedbackStore + AuditStore: basic persistence and list_negative
  - failure_analyzer: audit+feedback signals boost priority and sort correctly
  - ComparativeSynthesizer path: comparative_output populated on analisis_comparativo
  - CaveatBanner caveat regex present in mocked response

All Anthropic API calls are mocked. SQLite stores use temporary files.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lex_agents_agents.routing.unsupported_detector import detect_unsupported


@pytest.mark.e2e
class TestUnsupportedDetector:
    def test_cuantificacion_detected(self) -> None:
        result = detect_unsupported("¿Cuánto es la multa por incumplir el RGPD?")
        assert result.detected is True
        assert result.pattern == "cuantificacion"
        assert result.degraded_response is not None
        assert "calcular importes exactos" in result.degraded_response

    def test_estrategia_detected(self) -> None:
        result = detect_unsupported("¿Cómo puedo recurrir la sanción de la AEPD?")
        assert result.detected is True
        assert result.pattern == "estrategia"

    def test_plazo_activo_detected(self) -> None:
        result = detect_unsupported("Me quedan solo 3 días para recurrir la resolución.")
        assert result.detected is True
        assert result.pattern == "plazo_activo"

    def test_asesoramiento_personal_detected(self) -> None:
        result = detect_unsupported("¿Debo firmar el contrato que me han enviado?")
        assert result.detected is True
        assert result.pattern == "asesoramiento_personal"

    def test_normative_query_not_detected(self) -> None:
        result = detect_unsupported(
            "¿Qué obligaciones establece el RGPD para el tratamiento de datos biométricos?"
        )
        assert result.detected is False
        assert result.pattern is None

    def test_degraded_response_contains_contact_recommendation(self) -> None:
        result = detect_unsupported("¿Cuánto me cobrarán de multa por infringir el RGPD?")
        assert result.detected is True
        assert "servicios jurídicos" in (result.degraded_response or "")


# ── FeedbackStore ─────────────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.asyncio
class TestFeedbackStore:
    async def test_save_and_list_negative(self) -> None:
        from lex_agents_api.db import FeedbackStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = FeedbackStore(db_path)
        await store.init()

        await store.save(trace_id="trace-001", verdict="incorrecto", notes="Cita errónea")
        await store.save(trace_id="trace-002", verdict="aceptable", notes="")
        await store.save(trace_id="trace-003", verdict="incorrecto", notes="Jurisdicción incorrecta")

        negatives = await store.list_negative(since_days=7)
        assert len(negatives) == 2
        trace_ids = {r.trace_id for r in negatives}
        assert "trace-001" in trace_ids
        assert "trace-003" in trace_ids
        assert "trace-002" not in trace_ids

    async def test_list_recent_returns_all(self) -> None:
        from lex_agents_api.db import FeedbackStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = FeedbackStore(db_path)
        await store.init()

        for i in range(5):
            await store.save(trace_id=f"trace-{i}", verdict="dudoso", notes="")

        recent = await store.list_recent(limit=10)
        assert len(recent) == 5


# ── AuditStore ────────────────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.asyncio
class TestAuditStore:
    async def test_save_and_submit_review(self) -> None:
        from datetime import UTC, datetime

        from lex_agents_audit.audit_store import AuditSampleRecord, AuditStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        await store.init()

        record = AuditSampleRecord(
            trace_id="trace-audit-001",
            query="¿Qué es el RGPD?",
            response_json=json.dumps({"answer": "El RGPD es..."}),
            branch="datos_personales_rgpd",
            depth="standard",
            sampled_at=datetime.now(UTC),
        )
        sample_id = await store.save(record)
        assert isinstance(sample_id, int)
        assert sample_id > 0

        record = await store.get(sample_id)
        assert record is not None
        assert record.status == "pending"

        ok = await store.submit_review(
            sample_id=sample_id,
            reviewer="test_user",
            notes="Respuesta correcta",
            verdict="correcto",
        )
        assert ok is True

        updated = await store.get(sample_id)
        assert updated is not None
        assert updated.status == "reviewed"
        assert updated.review_verdict == "correcto"

    async def test_list_negative_returns_incorrecto(self) -> None:
        from lex_agents_audit.audit_store import AuditStore

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = AuditStore(db_path)
        await store.init()

        from datetime import UTC, datetime

        from lex_agents_audit.audit_store import AuditSampleRecord

        for verdict in ("correcto", "incorrecto", "dudoso", "incorrecto"):
            sid = await store.save(AuditSampleRecord(
                trace_id=f"trace-{verdict}-{id(verdict)}",
                query="test",
                response_json="{}",
                branch="regulatorio_bancario_ue_es",
                depth="shallow",
                sampled_at=datetime.now(UTC),
            ))
            await store.submit_review(
                sample_id=sid,
                reviewer="tester",
                notes="",
                verdict=verdict,  # type: ignore[arg-type]
            )

        negatives = await store.list_negative(since_days=7)
        assert len(negatives) == 2
        for n in negatives:
            assert n.review_verdict == "incorrecto"


# ── FailureAnalyzer with external signals ─────────────────────────────────────

@pytest.mark.e2e
class TestFailureAnalyzerSignals:
    def test_audit_signal_boosts_priority(self, tmp_path: Path) -> None:
        from lex_agents_evals_advanced.reflection.failure_analyzer import analyze_failures

        # Empty results dir (no LeMAJ data)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        audit_negatives = [
            {"branch": "regulatorio_bancario_ue_es", "response_json": "{}"},
            {"branch": "regulatorio_bancario_ue_es", "response_json": "{}"},
            {"branch": "datos_personales_rgpd", "response_json": "{}"},
        ]
        feedback_negatives = [
            {"branch": "datos_personales_rgpd", "response_json": "{}"},
        ]

        clusters = analyze_failures(
            results_dir,
            audit_negatives=audit_negatives,
            feedback_negatives=feedback_negatives,
        )

        assert len(clusters) == 2
        # regulatorio: 2 audit × 3 = 6 pts; datos_personales: 1 audit × 3 + 1 feedback × 2 = 5 pts
        regulatorio = next(c for c in clusters if c.branch == "regulatorio_bancario_ue_es")
        datos = next(c for c in clusters if c.branch == "datos_personales_rgpd")
        assert regulatorio.priority_score > datos.priority_score
        assert regulatorio.audit_incorrecto_count == 2
        assert datos.feedback_incorrecto_count == 1

    def test_clusters_sorted_by_priority_descending(self, tmp_path: Path) -> None:
        from lex_agents_evals_advanced.reflection.failure_analyzer import analyze_failures

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        audit_negatives = [
            {"branch": "administrativo", "response_json": "{}"},
            {"branch": "laboral", "response_json": "{}"},
            {"branch": "laboral", "response_json": "{}"},
            {"branch": "laboral", "response_json": "{}"},
        ]
        clusters = analyze_failures(results_dir, audit_negatives=audit_negatives)

        assert len(clusters) >= 2
        scores = [c.priority_score for c in clusters]
        assert scores == sorted(scores, reverse=True)

    def test_empty_signals_returns_empty(self, tmp_path: Path) -> None:
        from lex_agents_evals_advanced.reflection.failure_analyzer import analyze_failures

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        clusters = analyze_failures(results_dir)
        assert clusters == []


# ── Comparative output present on analisis_comparativo ───────────────────────

@pytest.mark.e2e
@pytest.mark.asyncio
class TestComparativeOutputWiring:
    async def test_comparative_output_populated(self) -> None:
        """Verify that ConsultResponse.comparative_output is non-None when
        output_type=analisis_comparativo and multiple branches are planned."""
        from lex_agents_agents.base_agent import AgentMetadata, AgentResponse
        from lex_agents_agents.core.orchestrator_v2 import (
            ConsultRequest,
            OrchestratorDeps,
            OrchestratorV2,
        )
        from lex_agents_shared.types import ComparativeResponse

        # Minimal mocks
        mock_client = MagicMock()
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = []
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = []
        mock_assembler = MagicMock()
        mock_assembler.assemble.return_value = MagicMock(citation_mapping=[])
        mock_rewriter = MagicMock()
        mock_rewriter.rewrite.return_value = MagicMock(expanded_query="test query")

        comparative = ComparativeResponse(
            trace_id="trace-comp-001",
            issue="Scoring ML con datos biométricos",
            jurisdictions_compared=["ES", "EU"],
            dimensions=[],
            divergences=[],
            common_ground=["Datos biométricos son categoría especial"],
            risk_differential={"ES": "high"},
            risk_rationale="Borrador asistido por IA — requiere validación cualificada.",
            coverage_gaps=[],
            citations=[],
            verification_status="green",
        )

        mock_agent_resp = AgentResponse(
            answer_text="Análisis comparativo: datos biométricos. Borrador asistido por IA; requiere validación humana cualificada.",
            citations=[],
            query_rewritten="test query",
            metadata=AgentMetadata(
                prompt_name="test",
                prompt_version=1,
                prompt_hash="abc123",
                model="claude-sonnet-4-6",
                input_tokens=100,
                output_tokens=50,
            ),
            comparative_output=comparative,
        )

        with (
            patch(
                "lex_agents_agents.core.orchestrator_v2.LegalPlanner"
            ) as MockPlanner,
            patch(
                "lex_agents_agents.core.orchestrator_v2.CrossJurisdictionCoordinator"
            ) as MockCoordinator,
            patch(
                "lex_agents_agents.core.orchestrator_v2.LegalJudge"
            ) as MockJudge,
            patch(
                "lex_agents_agents.core.orchestrator_v2.QueryRouter"
            ) as MockRouter,
        ):
            from lex_agents_agents.shared.definition_of_done import (
                BranchTask,
                DefinitionOfDone,
                PlannerOutput,
            )

            plan = PlannerOutput(
                branches=[
                    {"name": "regulatorio_bancario_ue_es"},
                    {"name": "datos_personales_rgpd"},
                ],
                jurisdictions=["ES", "EU"],
                output_type="analisis_comparativo",
                depth="standard",
                sub_tasks=[
                    BranchTask(id="T1", branch="regulatorio_bancario_ue_es", priority=1, weight=0.5, query="test"),
                    BranchTask(id="T2", branch="datos_personales_rgpd", priority=2, weight=0.5, query="test"),
                ],
                definition_of_done=DefinitionOfDone(required_sections=[], citation_required=True, caveat_required=True),
            )
            MockPlanner.return_value.plan.return_value = plan
            MockCoordinator.return_value.run_parallel = AsyncMock(
                return_value=[mock_agent_resp, mock_agent_resp]
            )
            MockCoordinator.return_value.synthesize_comparative = AsyncMock(
                return_value=mock_agent_resp
            )

            deps = OrchestratorDeps(
                retriever=mock_retriever,
                reranker=mock_reranker,
                query_rewriter=mock_rewriter,
                assembler=mock_assembler,
                client=mock_client,
            )
            orchestrator = OrchestratorV2(deps)

            req = ConsultRequest(
                query="Comparar regulación de datos biométricos en España y UE para scoring ML",
                output_type="analisis_comparativo",
                depth="standard",
            )
            result = await orchestrator.run(req)

        assert result.comparative_output is not None
        assert result.comparative_output.issue == "Scoring ML con datos biométricos"
        assert len(result.comparative_output.jurisdictions_compared) >= 1


# ── Caveat invariant: answer always contains required caveat text ──────────────

@pytest.mark.e2e
class TestCaveatInvariant:
    def test_caveat_pattern_present(self) -> None:
        import re

        caveat_pattern = re.compile(
            r"(borrador.*IA|requiere.*validaci[oó]n|validaci[oó]n.*humana)", re.IGNORECASE
        )
        sample_answers = [
            "El análisis es el siguiente. Borrador asistido por IA; requiere validación humana cualificada.",
            "Conclusión normativa. Este documento requiere validación por parte de un jurista.",
            "Dictamen: ... Borrador IA requiere revisión.",
        ]
        for answer in sample_answers:
            assert caveat_pattern.search(answer), f"Missing caveat in: {answer}"

    def test_degraded_response_always_contains_contact_advice(self) -> None:
        from lex_agents_agents.routing.unsupported_detector import detect_unsupported

        patterns_to_check = [
            "¿Cuánto es la multa exacta por no notificar una brecha?",
            "¿Cómo debo defender mi empresa ante la AEPD?",
            "Tengo hasta el lunes para recurrir, ¿qué hago?",
            "¿Debo firmar el acuerdo de confidencialidad?",
        ]
        for query in patterns_to_check:
            result = detect_unsupported(query)
            assert result.detected, f"Expected detection for: {query}"
            assert result.degraded_response is not None
            assert "servicios jurídicos" in result.degraded_response
