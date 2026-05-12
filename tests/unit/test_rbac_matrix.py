"""RBAC matrix tests: role × governance/audit-trail endpoints → expected HTTP status."""

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
    client = TestClient(app, raise_server_exceptions=False)
    return client


# Endpoints that require operator|admin
_OP_ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/governance/proposals"),
    ("GET", "/api/v1/admin/governance/sources"),
    ("GET", "/api/v1/admin/governance/recent-decisions"),
    ("GET", "/api/v1/admin/audit-trail"),
    ("GET", "/api/v1/admin/audit-trail/verify"),
]

# Endpoints that require admin only
_ADMIN_ONLY_ENDPOINTS = [
    ("POST", "/api/v1/admin/audit-trail/export"),
]


class TestOperatorAdminEndpoints:
    @pytest.mark.parametrize("method,path", _OP_ADMIN_ENDPOINTS)
    def test_analyst_gets_403(self, method: str, path: str) -> None:
        with _make_client("analyst") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code in (403, 404, 422, 500)

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


class TestAdminOnlyEndpoints:
    @pytest.mark.parametrize("method,path", _ADMIN_ONLY_ENDPOINTS)
    def test_operator_gets_403(self, method: str, path: str) -> None:
        with _make_client("operator") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code in (403, 404, 422, 500)

    @pytest.mark.parametrize("method,path", _ADMIN_ONLY_ENDPOINTS)
    def test_admin_not_403(self, method: str, path: str) -> None:
        with _make_client("admin") as client:
            resp = getattr(client, method.lower())(path)
        assert resp.status_code != 403
