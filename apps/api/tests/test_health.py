"""Tests for /health and /version endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from lex_agents_api.main import create_app
from lex_agents_api.settings import Settings


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        env="dev",
        log_level="DEBUG",
        anthropic_api_key="sk-ant-test",
        qdrant_url="http://localhost:6333",
        version="0.1.0-test",
        commit_sha="abc123",
        build_time="2026-05-10T00:00:00Z",
    )


@pytest.fixture()
def client(test_settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[__import__(
        "lex_agents_api.settings", fromlist=["get_settings"]
    ).get_settings] = lambda: test_settings
    return TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    def test_health_returns_200_when_qdrant_healthy(self, client: TestClient) -> None:
        with patch("lex_agents_api.routers.health._get_qdrant_status", return_value="healthy"):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["deps_status"]["qdrant"] == "healthy"
        assert data["deps_status"]["anthropic_api"] == "configured"

    def test_health_returns_503_when_qdrant_unavailable(self, client: TestClient) -> None:
        with patch("lex_agents_api.routers.health._get_qdrant_status", return_value="unavailable"):
            resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unavailable"

    def test_health_degraded_when_no_anthropic_key(self) -> None:
        settings = Settings(env="dev", anthropic_api_key="", qdrant_url="http://localhost:6333")
        app = create_app()
        from lex_agents_api.settings import get_settings
        app.dependency_overrides[get_settings] = lambda: settings
        c = TestClient(app, raise_server_exceptions=False)
        with patch("lex_agents_api.routers.health._get_qdrant_status", return_value="healthy"):
            resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["deps_status"]["anthropic_api"] == "not_configured"
        assert resp.json()["status"] == "degraded"

    def test_correlation_id_header_returned(self, client: TestClient) -> None:
        with patch("lex_agents_api.routers.health._get_qdrant_status", return_value="healthy"):
            resp = client.get("/health", headers={"X-Correlation-ID": "test-cid-123"})
        assert resp.headers.get("x-correlation-id") == "test-cid-123"


class TestVersionEndpoint:
    def test_version_returns_build_metadata(self, client: TestClient) -> None:
        resp = client.get("/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.1.0-test"
        assert data["commit_sha"] == "abc123"
        assert data["build_time"] == "2026-05-10T00:00:00Z"
        assert "python_version" in data
