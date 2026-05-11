"""Tests for POST /api/v1/consult and GET /api/v1/consult/{trace_id}."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lex_agents_api.db import ConsultationRecord, ConsultationStore
from lex_agents_api.main import create_app
from lex_agents_api.routers.consult import get_orchestrator, get_store
from lex_agents_api.settings import Settings, get_settings
from lex_agents_agents.orchestrator import ConsultResponse


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        env="dev",
        anthropic_api_key="sk-ant-test",
        qdrant_url="http://localhost:6333",
        agents_package_enabled=True,
    )


def _make_consult_response(trace_id: str = "test-trace-abc") -> ConsultResponse:
    from lex_agents_shared.types import CitationMapping, VerificationReport
    return ConsultResponse(
        trace_id=trace_id,
        answer="## 1. Cuestión planteada\nRatio CET1 [REF:1]",
        citations=[
            CitationMapping(
                index=1,
                chunk_id="chunk_001",
                source_id="32013R0575",
                hierarchy_path="CRR > Art. 92",
                fragment_text="artículo 92 ratio 4,5%",
            )
        ],
        verification=VerificationReport(
            response_id=trace_id,
            claims_total=1,
            claims_passed=1,
            claims_failed=0,
            claims_uncertain=0,
            llm_calls_made=0,
            uncited_claims=[],
            broken_refs=[],
            status="green",
        ),
        query_rewritten="expanded CET1 CRR query",
        routing={"branch": "regulatorio_bancario_ue_es", "depth": "standard"},
        metadata={"prompt_version": 1, "model": "claude-opus-4-7", "latency_ms": 1500},
    )


@pytest.fixture()
def mock_orchestrator() -> MagicMock:
    orch = MagicMock()
    orch.run = AsyncMock(return_value=_make_consult_response())
    return orch


@pytest.fixture()
def mock_store() -> MagicMock:
    store = MagicMock(spec=ConsultationStore)
    store.save = AsyncMock()
    store.get = AsyncMock(return_value=None)
    store.list_recent = AsyncMock(return_value=[])
    return store


@pytest.fixture()
def client(
    test_settings: Settings,
    mock_orchestrator: MagicMock,
    mock_store: MagicMock,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_store] = lambda: mock_store
    return TestClient(app, raise_server_exceptions=True)


class TestConsult200ReturnsTraceId:
    def test_post_consult_returns_200(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/consult",
            json={"query": "¿Cuáles son los requisitos CET1 del CRR?"},
        )
        assert resp.status_code == 200

    def test_response_has_trace_id(self, client: TestClient) -> None:
        resp = client.post("/api/v1/consult", json={"query": "CET1 CRR"})
        data = resp.json()
        assert "trace_id" in data
        assert data["trace_id"]

    def test_response_has_answer(self, client: TestClient) -> None:
        resp = client.post("/api/v1/consult", json={"query": "CET1 CRR"})
        data = resp.json()
        assert "answer" in data
        assert len(data["answer"]) > 0


class TestConsult200VerificationStatusGreen:
    def test_verification_status_green(self, client: TestClient) -> None:
        resp = client.post("/api/v1/consult", json={"query": "CET1 CRR"})
        data = resp.json()
        assert data["verification"]["status"] == "green"
        assert data["verification"]["broken_refs"] == []
        assert data["verification"]["uncited_claims"] == []


class TestGetConsultByTraceId:
    def test_404_when_not_found(
        self, client: TestClient, mock_store: MagicMock
    ) -> None:
        mock_store.get = AsyncMock(return_value=None)
        resp = client.get("/api/v1/consult/nonexistent-trace")
        assert resp.status_code == 404

    def test_returns_stored_consultation(
        self, client: TestClient, mock_store: MagicMock
    ) -> None:
        consult_resp = _make_consult_response("stored-trace-123")
        record = ConsultationRecord(
            trace_id="stored-trace-123",
            created_at=datetime.now(timezone.utc),
            query="CET1 query",
            response_json=consult_resp.model_dump_json(),
        )
        mock_store.get = AsyncMock(return_value=record)

        resp = client.get("/api/v1/consult/stored-trace-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "stored-trace-123"
        assert "answer" in data
