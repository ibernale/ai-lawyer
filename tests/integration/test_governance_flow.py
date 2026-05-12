"""Integration tests: governance actions generate correct audit entries."""

from __future__ import annotations

import pytest
from lex_agents_audit.audit_trail import AuditTrailManager


@pytest.fixture
async def mgr(tmp_path):
    m = AuditTrailManager(str(tmp_path / "gov.db"))
    await m.init()
    return m


class TestSourcePauseFlow:
    async def test_pause_creates_audit_entry_with_before_after(
        self, mgr: AuditTrailManager
    ) -> None:
        sources = await mgr.list_sources()
        boe_before = next(s for s in sources if s.source_id == "boe")
        assert boe_before.status == "active"

        await mgr.set_source_status("boe", "paused", paused_by="op1", paused_reason="scheduled maintenance")
        entry_id = await mgr.log(
            "source.pause", "source", "op1", "operator",
            "scheduled maintenance",
            target_id="boe",
            before={"status": "active"},
            after={"status": "paused"},
        )

        entry = await mgr.get_entry(entry_id)
        assert entry is not None
        assert entry.action_type == "source.pause"
        assert entry.target_id == "boe"
        assert '"active"' in (entry.before_state or "")
        assert '"paused"' in (entry.after_state or "")

    async def test_chain_remains_valid_after_multiple_actions(
        self, mgr: AuditTrailManager
    ) -> None:
        await mgr.set_source_status("boe", "paused", paused_by="op1", paused_reason="r1")
        await mgr.log("source.pause", "source", "op1", "operator", "r1", target_id="boe")

        await mgr.set_source_status("boe", "active")
        await mgr.log("source.resume", "source", "op1", "operator", "maintenance done", target_id="boe")

        result = await mgr.verify_chain()
        assert result.valid is True
        assert result.total == 2


class TestExportMetaAudit:
    async def test_export_audit_trail_logs_export_action(
        self, mgr: AuditTrailManager
    ) -> None:
        await mgr.log("source.pause", "source", "u", "admin", "test")
        entries_before = await mgr.get_history()
        assert len(entries_before) == 1

        # Simulate export meta-audit
        await mgr.log(
            "export.audit_trail", "audit_trail", "admin1", "admin",
            "Manual export requested (format=csv)",
            after={"format": "csv", "rows_exported": 1},
        )
        entries_after = await mgr.get_history()
        assert len(entries_after) == 2
        export_entry = entries_after[0]  # most recent first
        assert export_entry.action_type == "export.audit_trail"
        assert "csv" in (export_entry.after_state or "")
