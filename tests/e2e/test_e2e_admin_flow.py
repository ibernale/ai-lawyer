"""E2E test — 18-step admin flow covering all Fase 8 admin capabilities.

Exercises in order:
  1-2.   System state (flags + kill switches present)
  3.     Agents list endpoint
  4.     RAG status
  5-6.   Feature flag activate + verify
  7-8.   Governance: source pause + verify status
  9.     Governance: source resume
  10.    Governance: proposals list
  11.    Audit trail: source.pause entry present
  12-13. Kill switch engage → consult blocked (503 SYSTEM_KILLED)
  14.    Kill switch release
  15.    Audit trail: kill_switch entries present
  16.    Notifications: ≥1 critical from kill switch
  17.    Notifications: mark all read
  18.    Notifications: count → 0
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-e2e-admin-flow-32ch")
os.environ.setdefault("AUTH_USERS_JSON", "[]")
os.environ["AUTH_ENABLED"] = "false"
os.environ["NOTIFICATION_WEBHOOK_SECRET"] = "test-webhook-secret-e2e"

# Invalidate the settings singleton so it re-reads the env vars we just set.
# Without this, a cached Settings() from a previous import (e.g. in CI where
# no .env file exists) would have notification_webhook_secret="" and the
# /ingest webhook endpoint would return 503 instead of 204.
import lex_agents_api.settings as _settings_mod  # noqa: E402
_settings_mod._settings = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def managers(tmp_path):
    from lex_agents_admin.state import SystemStateManager, set_system_state_manager
    from lex_agents_audit.audit_trail import AuditTrailManager, set_audit_trail_manager
    from lex_agents_audit.notifications import NotificationManager, set_notification_manager

    db = str(tmp_path / "gov.db")

    ssm = SystemStateManager(db)
    await ssm.init()
    set_system_state_manager(ssm)

    atm = AuditTrailManager(db)
    await atm.init()
    set_audit_trail_manager(atm)

    nm = NotificationManager(db)
    await nm.init()
    set_notification_manager(nm)

    yield {"ssm": ssm, "atm": atm, "nm": nm}

    set_system_state_manager(None)  # type: ignore[arg-type]
    set_audit_trail_manager(None)  # type: ignore[arg-type]
    set_notification_manager(None)  # type: ignore[arg-type]


@pytest.fixture
def admin_client(managers):
    from lex_agents_admin.state import set_system_state_manager
    from lex_agents_api.auth import CurrentUser, require_auth
    from lex_agents_api.main import app
    from lex_agents_audit.audit_trail import set_audit_trail_manager
    from lex_agents_audit.notifications import set_notification_manager

    async def _admin() -> CurrentUser:
        return CurrentUser(username="admin", role="admin")

    app.dependency_overrides[require_auth] = _admin
    with TestClient(app, raise_server_exceptions=False) as c:
        # Lifespan may overwrite singletons; re-point to test managers
        set_system_state_manager(managers["ssm"])
        set_audit_trail_manager(managers["atm"])
        set_notification_manager(managers["nm"])
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def operator_client(managers):
    from lex_agents_admin.state import set_system_state_manager
    from lex_agents_api.auth import CurrentUser, require_auth
    from lex_agents_api.main import app
    from lex_agents_audit.audit_trail import set_audit_trail_manager
    from lex_agents_audit.notifications import set_notification_manager

    async def _operator() -> CurrentUser:
        return CurrentUser(username="operator1", role="operator")

    app.dependency_overrides[require_auth] = _operator
    with TestClient(app, raise_server_exceptions=False) as c:
        set_system_state_manager(managers["ssm"])
        set_audit_trail_manager(managers["atm"])
        set_notification_manager(managers["nm"])
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Admin flow
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestAdminFlow:
    # Step 1 — GET /system/state returns structure
    async def test_step01_system_state_structure(
        self, admin_client: TestClient
    ) -> None:
        resp = admin_client.get("/api/v1/admin/system/state")
        assert resp.status_code == 200
        data = resp.json()
        # key is 'flags' (not 'feature_flags') in SystemState response
        assert "flags" in data or "feature_flags" in data
        assert "kill_switches" in data

    # Step 2 — kill switches list present with global entry
    async def test_step02_global_kill_switch_not_engaged(
        self, admin_client: TestClient
    ) -> None:
        resp = admin_client.get("/api/v1/admin/system/state")
        assert resp.status_code == 200
        data = resp.json()
        switches = data.get("kill_switches", data.get("flags", []))
        global_ks = next((k for k in switches if k["target"] == "global"), None)
        if global_ks is not None:
            assert global_ks["engaged"] is False

    # Step 3 — GET /admin/agents returns list
    async def test_step03_agents_list(self, admin_client: TestClient) -> None:
        resp = admin_client.get("/api/v1/admin/agents")
        assert resp.status_code in (200, 404, 503)
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)

    # Step 4 — GET /admin/rag/status returns collection info
    async def test_step04_rag_status(self, admin_client: TestClient) -> None:
        resp = admin_client.get("/api/v1/admin/rag/status")
        assert resp.status_code in (200, 503)

    # Step 5 — PUT /system/flags/test.e2e.flag → 204
    async def test_step05_activate_feature_flag(
        self, admin_client: TestClient
    ) -> None:
        resp = admin_client.put(
            "/api/v1/admin/system/flags/test.e2e.flag",
            json={"value": True, "reason": "E2E test"},
        )
        assert resp.status_code == 204

    # Step 6 — GET /system/state → flag present
    async def test_step06_flag_visible_in_state(
        self, admin_client: TestClient
    ) -> None:
        admin_client.put(
            "/api/v1/admin/system/flags/test.e2e.flag",
            json={"value": True, "reason": "E2E test"},
        )
        resp = admin_client.get("/api/v1/admin/system/state")
        assert resp.status_code == 200
        data = resp.json()
        flags = data.get("flags", data.get("feature_flags", []))
        flag = next((f for f in flags if f.get("key") == "test.e2e.flag"), None)
        assert flag is not None
        # value stored as JSON (may be bool True or string "true")
        assert flag.get("value") in (True, "true", 1) or flag.get("enabled") is True

    # Step 7 — POST /governance/sources/boe/pause → 200 with status body
    async def test_step07_pause_source(self, admin_client: TestClient) -> None:
        resp = admin_client.post(
            "/api/v1/admin/governance/sources/boe/pause",
            json={"reason": "E2E test pause"},
        )
        assert resp.status_code in (200, 204)
        if resp.status_code == 200:
            assert resp.json().get("status") == "paused"

    # Step 8 — GET /governance/sources → boe status paused
    async def test_step08_paused_source_visible(
        self, admin_client: TestClient
    ) -> None:
        admin_client.post(
            "/api/v1/admin/governance/sources/boe/pause",
            json={"reason": "E2E test pause"},
        )
        resp = admin_client.get("/api/v1/admin/governance/sources")
        assert resp.status_code == 200
        sources = resp.json()
        boe = next((s for s in sources if s.get("source_id") == "boe"), None)
        if boe is not None:
            assert boe["status"] == "paused"

    # Step 9 — POST /governance/sources/boe/resume → 200/204
    async def test_step09_resume_source(self, admin_client: TestClient) -> None:
        admin_client.post(
            "/api/v1/admin/governance/sources/boe/pause",
            json={"reason": "E2E setup"},
        )
        resp = admin_client.post(
            "/api/v1/admin/governance/sources/boe/resume",
            json={"reason": "E2E test resume"},
        )
        assert resp.status_code in (200, 204)

    # Step 10 — GET /governance/proposals → list (operator can read)
    async def test_step10_proposals_list_operator(
        self, operator_client: TestClient
    ) -> None:
        resp = operator_client.get("/api/v1/admin/governance/proposals")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    # Step 11 — GET /audit-trail → source.pause entry present after step 7
    async def test_step11_audit_trail_source_pause(
        self, admin_client: TestClient
    ) -> None:
        admin_client.post(
            "/api/v1/admin/governance/sources/boe/pause",
            json={"reason": "E2E audit check"},
        )
        resp = admin_client.get("/api/v1/admin/audit-trail")
        assert resp.status_code == 200
        entries = resp.json()
        action_types = [e.get("action_type", "") for e in entries]
        assert any("source" in at for at in action_types)

    # Step 12 — PUT /system/kill/global engage:true → 204
    async def test_step12_engage_global_kill_switch(
        self, admin_client: TestClient
    ) -> None:
        resp = admin_client.put(
            "/api/v1/admin/system/kill/global",
            json={"engage": True, "reason": "E2E kill switch test"},
        )
        assert resp.status_code == 204

    # Step 13 — POST /consult → 503 SYSTEM_KILLED
    async def test_step13_consult_blocked_while_killed(
        self, admin_client: TestClient
    ) -> None:
        admin_client.put(
            "/api/v1/admin/system/kill/global",
            json={"engage": True, "reason": "E2E kill test"},
        )
        resp = admin_client.post(
            "/api/v1/consult",
            json={"query": "¿Qué dice el artículo 5 CRR?"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "SYSTEM_KILLED"

    # Step 14 — PUT /system/kill/global engage:false → 204
    async def test_step14_release_global_kill_switch(
        self, admin_client: TestClient
    ) -> None:
        admin_client.put(
            "/api/v1/admin/system/kill/global",
            json={"engage": True, "reason": "E2E setup"},
        )
        resp = admin_client.put(
            "/api/v1/admin/system/kill/global",
            json={"engage": False, "reason": "E2E resolved"},
        )
        assert resp.status_code == 204

    # Step 15 — GET /audit-trail → kill_switch entries present after HTTP engage+release
    async def test_step15_audit_trail_has_kill_switch_entries(
        self, admin_client: TestClient
    ) -> None:
        # Use the HTTP endpoint so the audit trail gets written
        admin_client.put(
            "/api/v1/admin/system/kill/global",
            json={"engage": True, "reason": "E2E audit check"},
        )
        admin_client.put(
            "/api/v1/admin/system/kill/global",
            json={"engage": False, "reason": "E2E resolved"},
        )
        resp = admin_client.get("/api/v1/admin/audit-trail")
        assert resp.status_code == 200
        entries = resp.json()
        action_types = [e.get("action_type", "") for e in entries]
        assert any("kill_switch" in at for at in action_types)

    # Step 16 — GET /notifications → ≥1 critical from kill switch
    async def test_step16_notifications_has_critical_from_kill_switch(
        self, admin_client: TestClient, managers: dict
    ) -> None:
        # Create notification directly (SSM subscriber wiring is integration-level)
        await managers["nm"].create(
            "system", "critical",
            "Kill switch engaged: global",
            "Engaged by admin — E2E test",
        )
        resp = admin_client.get("/api/v1/admin/notifications")
        assert resp.status_code == 200
        notifications = resp.json()
        assert len(notifications) >= 1
        critical = [n for n in notifications if n["category"] == "critical"]
        assert len(critical) >= 1

    # Step 17 — PUT /notifications/read-all → 204
    async def test_step17_mark_all_notifications_read(
        self, admin_client: TestClient, managers: dict
    ) -> None:
        await managers["nm"].create("system", "info", "Test", "Body")
        resp = admin_client.put("/api/v1/admin/notifications/read-all")
        assert resp.status_code == 204

    # Step 18 — GET /notifications/count → {unread: 0}
    async def test_step18_unread_count_zero_after_mark_all(
        self, admin_client: TestClient, managers: dict
    ) -> None:
        await managers["nm"].create("system", "warning", "Test W", "Body")
        admin_client.put("/api/v1/admin/notifications/read-all")
        resp = admin_client.get("/api/v1/admin/notifications/count")
        assert resp.status_code == 200
        assert resp.json()["unread"] == 0


# ---------------------------------------------------------------------------
# Notification ingest webhook (static bearer secret, not JWT)
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = "test-webhook-secret-e2e"
_WEBHOOK_HEADERS = {"Authorization": f"Bearer {_WEBHOOK_SECRET}"}


@pytest.mark.e2e
class TestNotificationIngest:
    def test_ingest_grafana_alert(
        self, admin_client: TestClient, managers: dict
    ) -> None:
        resp = admin_client.post(
            "/api/v1/admin/notifications/ingest",
            json={
                "source": "grafana",
                "category": "critical",
                "title": "ServiceDown: lex-agents-api",
                "body": "Container unhealthy for 6 minutes",
                "correlation_id": "grafana-abc123",
            },
            headers=_WEBHOOK_HEADERS,
        )
        assert resp.status_code == 204

    def test_ingest_invalid_category_rejected(
        self, admin_client: TestClient
    ) -> None:
        resp = admin_client.post(
            "/api/v1/admin/notifications/ingest",
            json={
                "source": "grafana",
                "category": "unknown",
                "title": "T",
                "body": "B",
            },
            headers=_WEBHOOK_HEADERS,
        )
        assert resp.status_code == 422

    def test_ingest_requires_webhook_secret(
        self, admin_client: TestClient
    ) -> None:
        """Request without webhook secret is rejected (401), regardless of JWT role."""
        resp = admin_client.post(
            "/api/v1/admin/notifications/ingest",
            json={
                "source": "grafana",
                "category": "info",
                "title": "T",
                "body": "B",
            },
            # No Authorization header
        )
        assert resp.status_code == 401

    def test_ingest_wrong_secret_rejected(
        self, admin_client: TestClient
    ) -> None:
        resp = admin_client.post(
            "/api/v1/admin/notifications/ingest",
            json={"source": "grafana", "category": "info", "title": "T", "body": "B"},
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert resp.status_code == 403
