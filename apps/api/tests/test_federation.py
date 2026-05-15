"""Tests for POST /api/v1/admin/federation/aws-console-url."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from lex_agents_api.auth import CurrentUser
from lex_agents_api.main import create_app
from lex_agents_api.settings import Settings, get_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(**kwargs: object) -> Settings:
    base: dict[str, object] = {
        "env": "dev",
        "log_level": "DEBUG",
        "anthropic_api_key": "sk-ant-test",
        "qdrant_url": "http://localhost:6333",
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture()
def client_no_federation() -> TestClient:
    """Client where federation role ARNs are empty (dev default)."""
    app = create_app()
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client_federation_configured() -> TestClient:
    """Client where federation role ARNs are set (simulates prod)."""
    app = create_app()
    settings = _make_settings(
        federation_role_arn_admin="arn:aws:iam::123456789012:role/lex-agents-dev-federation-admin",
        federation_role_arn_operator="arn:aws:iam::123456789012:role/lex-agents-dev-federation-operator",
        federation_role_arn_viewer="arn:aws:iam::123456789012:role/lex-agents-dev-federation-viewer",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def _auth_user(role: str) -> CurrentUser:
    return CurrentUser(username=f"test_{role}", role=role)


# ---------------------------------------------------------------------------
# Tests: auth enforcement
# ---------------------------------------------------------------------------


def test_federation_requires_auth(client_no_federation: TestClient) -> None:
    res = client_no_federation.post(
        "/api/v1/admin/federation/aws-console-url",
        json={"service": "cloudwatch"},
    )
    assert res.status_code in (401, 403)


def test_federation_forbidden_for_analyst_role(client_no_federation: TestClient) -> None:
    """analyst role (legacy) must not access federation endpoint."""
    from lex_agents_api.auth import require_auth

    app = create_app()
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    # Inject analyst user via require_auth; require_role will reject it with 403
    app.dependency_overrides[require_auth] = lambda: CurrentUser(username="test_analyst", role="analyst")
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/v1/admin/federation/aws-console-url",
        json={"service": "cloudwatch"},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Tests: federation disabled (no ARNs configured)
# ---------------------------------------------------------------------------


def test_federation_503_when_not_configured(client_no_federation: TestClient) -> None:
    """Returns 503 when federation role ARNs are not set."""
    from lex_agents_api.auth import require_role

    app = create_app()
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    # Bypass actual RBAC to test the ARN check
    app.dependency_overrides[
        require_role("viewer", "operator", "admin")
    ] = lambda: CurrentUser(username="test_admin", role="admin")
    client = TestClient(app, raise_server_exceptions=False)

    res = client.post(
        "/api/v1/admin/federation/aws-console-url",
        json={"service": "cloudwatch"},
    )
    assert res.status_code == 503
    assert "federation" in res.json()["detail"].lower() or "configured" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tests: successful URL generation (mocked STS)
# ---------------------------------------------------------------------------


def test_federation_returns_url_for_admin(client_federation_configured: TestClient) -> None:
    """Admin role generates a federation URL successfully."""
    from lex_agents_api.auth import require_role

    app = create_app()
    settings = _make_settings(
        federation_role_arn_admin="arn:aws:iam::123456789012:role/lex-agents-dev-federation-admin",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[
        require_role("viewer", "operator", "admin")
    ] = lambda: CurrentUser(username="test_admin", role="admin")

    mock_creds = {
        "AccessKeyId": "ASIATEST",
        "SecretAccessKey": "secrettest",
        "SessionToken": "tokentest",
    }

    with (
        patch("boto3.client") as mock_boto3,
        patch(
            "lex_agents_api.routers.federation._build_signin_url",
            return_value="https://signin.aws.amazon.com/federation?Action=login&token=fake",
        ),
    ):
        sts_mock = MagicMock()
        sts_mock.assume_role.return_value = {"Credentials": mock_creds}
        mock_boto3.return_value = sts_mock

        client = TestClient(app, raise_server_exceptions=False)
        res = client.post(
            "/api/v1/admin/federation/aws-console-url",
            json={"service": "cloudwatch"},
        )

    assert res.status_code == 200
    data = res.json()
    assert "url" in data
    assert "signin.aws.amazon.com" in data["url"]


def test_federation_rejects_unknown_service(client_federation_configured: TestClient) -> None:
    from lex_agents_api.auth import require_role

    app = create_app()
    settings = _make_settings(
        federation_role_arn_operator="arn:aws:iam::123456789012:role/op",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[
        require_role("viewer", "operator", "admin")
    ] = lambda: CurrentUser(username="test_op", role="operator")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/v1/admin/federation/aws-console-url",
        json={"service": "invalid_service"},
    )
    assert res.status_code == 422  # pydantic validation on Literal type
