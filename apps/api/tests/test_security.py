"""Security pen-test suite — authorisation, IDOR, rate-limiting, error-message parity.

These tests exercise the security controls documented in ADR-0034 (auth) and Fase 10.4.
No external service is required; all heavy dependencies are mocked at the app-factory level.
"""

from __future__ import annotations

import json

import bcrypt
import pytest
from fastapi.testclient import TestClient
from lex_agents_api.main import create_app
from lex_agents_api.settings import Settings, get_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


def _build_users_json(users: list[dict[str, str]]) -> str:
    return json.dumps(users)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _admin_hash() -> str:
    return _make_password_hash("AdminPass1!")


@pytest.fixture()
def _viewer_hash() -> str:
    return _make_password_hash("ViewerPass1!")


@pytest.fixture()
def security_settings(_admin_hash: str, _viewer_hash: str) -> Settings:
    """Settings with two users: one admin and one analyst (viewer role)."""
    users = [
        {"username": "admin_user", "password_hash": _admin_hash, "role": "admin"},
        {"username": "viewer_user", "password_hash": _viewer_hash, "role": "analyst"},
    ]
    return Settings(
        env="dev",
        log_level="DEBUG",
        anthropic_api_key="sk-ant-test",
        qdrant_url="http://localhost:6333",
        auth_enabled=True,
        jwt_secret="test-secret-not-for-prod",
        jwt_expire_minutes=5,
        auth_users_json=_build_users_json(users),
    )


@pytest.fixture()
def client(security_settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: security_settings
    return TestClient(app, raise_server_exceptions=False)


def _get_token(client: TestClient, username: str, password: str) -> str:
    resp = client.post(
        "/auth/token",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAuthzEscalation:
    """Viewer-role token cannot reach admin-only endpoints (expect 403)."""

    def test_authz_escalation(self, client: TestClient, _viewer_hash: str) -> None:
        token = _get_token(client, "viewer_user", "ViewerPass1!")

        # Admin-only endpoint from ops router
        resp = client.get(
            "/api/v1/admin/agents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for analyst accessing /api/v1/admin/agents, got {resp.status_code}"
        )

    def test_authz_viewer_cannot_list_users(self, client: TestClient) -> None:
        token = _get_token(client, "viewer_user", "ViewerPass1!")

        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for analyst accessing /api/v1/admin/users, got {resp.status_code}"
        )

    def test_authz_admin_can_list_users(self, client: TestClient) -> None:
        token = _get_token(client, "admin_user", "AdminPass1!")

        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Admin should succeed (2xx) or get a 503 if the users manager is unavailable —
        # but must NOT get 403.
        assert resp.status_code != 403, (
            f"Admin role should not be forbidden from /api/v1/admin/users, got {resp.status_code}"
        )


class TestIdorSessionsCrossUser:
    """User A cannot list sessions of User B — IDOR check on admin users endpoint."""

    def test_idor_sessions_cross_user(self, client: TestClient) -> None:
        # viewer_user tries to access another user's sessions
        token = _get_token(client, "viewer_user", "ViewerPass1!")

        resp = client.get(
            "/api/v1/admin/users/admin_user/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Endpoint may not exist (404) or be forbidden (403) — either is acceptable.
        # What is NOT acceptable is a 200 that exposes another user's data.
        assert resp.status_code in (403, 404), (
            f"viewer_user must not reach admin_user's sessions; got {resp.status_code}"
        )

    def test_idor_own_sessions_still_forbidden_for_viewer(self, client: TestClient) -> None:
        """Admin /users/{username}/sessions is admin-only; even own username returns 403."""
        token = _get_token(client, "viewer_user", "ViewerPass1!")

        resp = client.get(
            "/api/v1/admin/users/viewer_user/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (403, 404), (
            f"viewer_user must not reach /admin/users/*/sessions; got {resp.status_code}"
        )


@pytest.mark.skip(reason="requires session management (Fase 10.4C)")
class TestTokenReplayAfterRevoke:
    """After revoking a session, subsequent requests with the same token return 401."""

    def test_token_replay_after_revoke(self, client: TestClient) -> None:
        token = _get_token(client, "admin_user", "AdminPass1!")

        # Get session list (assumes endpoint exists post Fase-10.4C)
        sessions_resp = client.get(
            "/api/v1/admin/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert sessions_resp.status_code == 200
        session_id = sessions_resp.json()[0]["id"]

        # Revoke the session
        revoke_resp = client.delete(
            f"/api/v1/admin/sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoke_resp.status_code in (200, 204)

        # The same token must now be rejected
        replay_resp = client.get(
            "/api/v1/admin/agents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert replay_resp.status_code == 401, (
            f"Revoked token must return 401; got {replay_resp.status_code}"
        )


class TestRateLimitLogin:
    """11 rapid POST /auth/token requests → the 11th returns 429."""

    def test_rate_limit_login(self, client: TestClient) -> None:
        # Use an intentionally wrong password so we don't need valid bcrypt hashes
        # pre-computed; we're testing rate-limiting, not authentication success.
        responses = []
        for _ in range(11):
            resp = client.post(
                "/auth/token",
                data={"username": "viewer_user", "password": "wrong-password"},
            )
            responses.append(resp.status_code)

        # The first N requests should be 401 (bad credentials), the 11th (or earlier)
        # should be 429 once the rate-limit window fills up.
        assert 429 in responses, (
            f"Expected at least one 429 after 11 rapid login attempts; got: {responses}"
        )


class TestBruteForceErrorIndistinguishable:
    """Wrong username and wrong password both return 401 with the same error body.

    This prevents username enumeration attacks.
    """

    def test_brute_force_error_indistinguishable(self, client: TestClient) -> None:
        wrong_username_resp = client.post(
            "/auth/token",
            data={"username": "nonexistent_user_xyz", "password": "AnyPassword1!"},
        )
        wrong_password_resp = client.post(
            "/auth/token",
            data={"username": "viewer_user", "password": "WrongPassword9!"},
        )

        assert wrong_username_resp.status_code == 401, (
            f"Expected 401 for unknown username; got {wrong_username_resp.status_code}"
        )
        assert wrong_password_resp.status_code == 401, (
            f"Expected 401 for wrong password; got {wrong_password_resp.status_code}"
        )

        # The error detail must be byte-for-byte identical to prevent enumeration.
        wrong_username_detail = wrong_username_resp.json().get("detail")
        wrong_password_detail = wrong_password_resp.json().get("detail")
        assert wrong_username_detail == wrong_password_detail, (
            "Error messages differ between unknown-username and wrong-password — "
            f"username enumeration risk! Got:\n"
            f"  unknown user : {wrong_username_detail!r}\n"
            f"  wrong passwd : {wrong_password_detail!r}"
        )
