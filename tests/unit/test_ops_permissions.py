"""RBAC matrix tests for ops and system endpoints."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only-32ch")
os.environ.setdefault("AUTH_USERS_JSON", "[]")
os.environ["AUTH_ENABLED"] = "false"


def _make_client(role: str) -> TestClient:
    from lex_agents_api.auth import CurrentUser, require_auth
    from lex_agents_api.main import app

    async def _override() -> CurrentUser:
        return CurrentUser(username=f"test_{role}", role=role)

    app.dependency_overrides[require_auth] = _override
    return TestClient(app, raise_server_exceptions=False)


# Endpoints requiring admin only
_ADMIN_ONLY_ENDPOINTS = [
    ("GET", "/api/v1/admin/agents"),
    ("GET", "/api/v1/admin/rag/status"),
    ("GET", "/api/v1/admin/memory/status"),
    ("GET", "/api/v1/admin/memory/procedural"),
]

# Endpoints requiring operator|admin
_OP_ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/system/state"),
]


class TestAdminOnlyOpsEndpoints:
    @pytest.mark.parametrize("method,path", _ADMIN_ONLY_ENDPOINTS)
    def test_analyst_gets_403(self, method: str, path: str) -> None:
        with _make_client("analyst") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", _ADMIN_ONLY_ENDPOINTS)
    def test_operator_gets_403(self, method: str, path: str) -> None:
        with _make_client("operator") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", _ADMIN_ONLY_ENDPOINTS)
    def test_admin_not_403(self, method: str, path: str) -> None:
        with _make_client("admin") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code != 403


class TestSystemStateEndpoints:
    @pytest.mark.parametrize("method,path", _OP_ADMIN_ENDPOINTS)
    def test_analyst_gets_403(self, method: str, path: str) -> None:
        with _make_client("analyst") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code == 403

    @pytest.mark.parametrize("method,path", _OP_ADMIN_ENDPOINTS)
    def test_operator_not_403(self, method: str, path: str) -> None:
        with _make_client("operator") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code != 403

    @pytest.mark.parametrize("method,path", _OP_ADMIN_ENDPOINTS)
    def test_admin_not_403(self, method: str, path: str) -> None:
        with _make_client("admin") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code != 403

    def test_analyst_cannot_set_flag(self) -> None:
        with _make_client("analyst") as client:
            resp = client.put(
                "/api/v1/admin/system/flags/test.flag",
                json={"value": True, "reason": "test"},
            )
        assert resp.status_code == 403

    def test_operator_cannot_set_flag(self) -> None:
        with _make_client("operator") as client:
            resp = client.put(
                "/api/v1/admin/system/flags/test.flag",
                json={"value": True, "reason": "test"},
            )
        assert resp.status_code == 403

    def test_analyst_cannot_engage_kill_switch(self) -> None:
        with _make_client("analyst") as client:
            resp = client.put(
                "/api/v1/admin/system/kill/global",
                json={"engage": True, "reason": "test"},
            )
        assert resp.status_code == 403

    def test_operator_cannot_engage_kill_switch(self) -> None:
        with _make_client("operator") as client:
            resp = client.put(
                "/api/v1/admin/system/kill/global",
                json={"engage": True, "reason": "test"},
            )
        assert resp.status_code == 403

    def test_admin_can_engage_kill_switch(self) -> None:
        with _make_client("admin") as client:
            resp = client.put(
                "/api/v1/admin/system/kill/global",
                json={"engage": True, "reason": "test incident"},
            )
        assert resp.status_code != 403
