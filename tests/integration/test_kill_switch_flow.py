"""Integration tests: global kill switch blocks /api/v1/consult."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only-32ch")
os.environ.setdefault("AUTH_USERS_JSON", "[]")
os.environ["AUTH_ENABLED"] = "false"


@pytest.fixture
async def state_mgr(tmp_path):
    from lex_agents_admin.state import SystemStateManager, set_system_state_manager
    m = SystemStateManager(str(tmp_path / "gov.db"))
    await m.init()
    set_system_state_manager(m)
    yield m
    set_system_state_manager(None)  # type: ignore[arg-type]


@pytest.fixture
def client(state_mgr):
    from lex_agents_admin.state import set_system_state_manager
    from lex_agents_api.auth import CurrentUser, require_auth
    from lex_agents_api.main import app

    async def _override() -> CurrentUser:
        return CurrentUser(username="test_user", role="analyst")

    app.dependency_overrides[require_auth] = _override
    with TestClient(app, raise_server_exceptions=False) as c:
        # Lifespan may have overwritten the singleton; re-point to our test manager
        set_system_state_manager(state_mgr)
        yield c
    app.dependency_overrides.clear()


class TestKillSwitchFlow:
    async def test_global_kill_switch_blocks_consult(
        self, client: TestClient, state_mgr
    ) -> None:
        await state_mgr.engage_kill_switch("global", actor="admin", reason="incident test")
        resp = client.post(
            "/api/v1/consult",
            json={"query": "¿Qué dice el artículo 5 de la Directiva CRR?"},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["detail"]["code"] == "SYSTEM_KILLED"

    async def test_release_allows_consult_through(
        self, client: TestClient, state_mgr
    ) -> None:
        await state_mgr.engage_kill_switch("global", actor="admin", reason="test")
        await state_mgr.release_kill_switch("global", actor="admin", reason="resolved")
        resp = client.post(
            "/api/v1/consult",
            json={"query": "¿Qué dice el artículo 5 de la Directiva CRR?"},
        )
        # After release the request should not be blocked by kill switch (may fail
        # for other reasons like missing Qdrant, but NOT with SYSTEM_KILLED 503)
        if resp.status_code == 503:
            assert resp.json().get("detail", {}).get("code") != "SYSTEM_KILLED"
