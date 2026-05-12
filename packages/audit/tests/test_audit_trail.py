"""Tests for AuditTrailManager — append-only enforcement and checksum chain."""

from __future__ import annotations

import aiosqlite
import pytest
from lex_agents_audit.audit_trail import AuditTrailManager


@pytest.fixture
async def mgr(tmp_path):
    m = AuditTrailManager(str(tmp_path / "governance.db"))
    await m.init()
    return m


class TestInit:
    async def test_creates_audit_trail_table(self, mgr: AuditTrailManager) -> None:
        async with aiosqlite.connect(mgr._db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cur:
                tables = {r[0] for r in await cur.fetchall()}
        assert "audit_trail" in tables
        assert "prompt_evolution_proposals" in tables
        assert "source_status" in tables

    async def test_seeds_four_sources(self, mgr: AuditTrailManager) -> None:
        sources = await mgr.list_sources()
        source_ids = {s.source_id for s in sources}
        assert source_ids == {"boe", "eur_lex", "cendoj", "bde"}

    async def test_idempotent_init(self, mgr: AuditTrailManager) -> None:
        await mgr.init()  # second call must not raise


class TestAppendOnly:
    async def test_update_rejected_by_trigger(self, mgr: AuditTrailManager) -> None:
        await mgr.log(
            "source.pause", "source", "admin1", "admin", "test pause",
            target_id="boe",
        )
        async with aiosqlite.connect(mgr._db_path) as db:
            with pytest.raises(Exception, match="append-only"):
                await db.execute("UPDATE audit_trail SET reason='tampered' WHERE id=1")

    async def test_delete_rejected_by_trigger(self, mgr: AuditTrailManager) -> None:
        await mgr.log(
            "source.resume", "source", "admin1", "admin", "test resume",
            target_id="boe",
        )
        async with aiosqlite.connect(mgr._db_path) as db:
            with pytest.raises(Exception, match="append-only"):
                await db.execute("DELETE FROM audit_trail WHERE id=1")


class TestLog:
    async def test_log_creates_entry(self, mgr: AuditTrailManager) -> None:
        row_id = await mgr.log(
            "source.pause", "source", "op1", "operator",
            "ingestion paused for maintenance",
            target_id="boe",
            before={"status": "active"},
            after={"status": "paused"},
        )
        assert row_id == 1
        entry = await mgr.get_entry(row_id)
        assert entry is not None
        assert entry.action_type == "source.pause"
        assert entry.actor_user_id == "op1"
        assert entry.reason == "ingestion paused for maintenance"
        assert entry.checksum_self is not None

    async def test_log_rejects_empty_reason(self, mgr: AuditTrailManager) -> None:
        with pytest.raises(ValueError, match="reason must not be empty"):
            await mgr.log("source.pause", "source", "op1", "operator", "  ")

    async def test_log_rejects_unknown_action_type(self, mgr: AuditTrailManager) -> None:
        with pytest.raises(ValueError, match="Unknown action_type"):
            await mgr.log("not.a.real.action", "thing", "u", "admin", "reason")

    async def test_multiple_entries_increment_id(self, mgr: AuditTrailManager) -> None:
        id1 = await mgr.log("source.pause", "source", "u", "admin", "r1", target_id="boe")
        id2 = await mgr.log("source.resume", "source", "u", "admin", "r2", target_id="boe")
        assert id2 > id1


class TestChecksumChain:
    async def test_fresh_chain_is_valid(self, mgr: AuditTrailManager) -> None:
        result = await mgr.verify_chain()
        assert result.valid is True
        assert result.total == 0

    async def test_chain_valid_after_entries(self, mgr: AuditTrailManager) -> None:
        for i in range(5):
            await mgr.log(
                "source.pause", "source", "u", "admin", f"reason {i}", target_id="boe"
            )
        result = await mgr.verify_chain()
        assert result.valid is True
        assert result.total == 5
        assert result.broken_at is None

    async def test_tampered_checksum_detected(self, mgr: AuditTrailManager) -> None:
        await mgr.log("source.pause", "source", "u", "admin", "r1", target_id="boe")
        await mgr.log("source.resume", "source", "u", "admin", "r2", target_id="boe")

        # INSERT a new row directly with a fabricated (wrong) checksum_self.
        # Triggers only block UPDATE and DELETE, so INSERT is allowed.
        # This simulates someone injecting a forged entry into the chain.
        async with aiosqlite.connect(mgr._db_path) as db:
            await db.execute(
                """INSERT INTO audit_trail
                   (timestamp, actor_user_id, actor_role, action_type, target_type,
                    reason, checksum_prev, checksum_self)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("2026-01-01T00:00:00", "attacker", "admin", "source.pause", "source",
                 "injected", "some_valid_prev", "FORGED_CHECKSUM"),
            )
            await db.commit()

        result = await mgr.verify_chain()
        assert result.valid is False
        assert result.broken_at is not None


class TestProposals:
    async def test_save_and_list_proposal(self, mgr: AuditTrailManager) -> None:
        row_id = await mgr.save_proposal(
            pr_url="https://github.com/test/repo/pull/42",
            specialist="bce",
            diff="--- a/bce.md\n+++ b/bce.md\n@@ -1 +1 @@\n-old\n+new",
            pr_number=42,
            motivating_cases="case 1 failed",
        )
        assert row_id == 1
        proposals = await mgr.list_proposals()
        assert len(proposals) == 1
        assert proposals[0].pr_url == "https://github.com/test/repo/pull/42"
        assert proposals[0].status == "pending"

    async def test_filter_by_status(self, mgr: AuditTrailManager) -> None:
        await mgr.save_proposal("http://a", "bce", "diff", pr_number=1)
        await mgr.save_proposal("http://b", "crr", "diff", pr_number=2)
        await mgr.update_proposal_status(1, "approved", "admin1", "looks good")

        pending = await mgr.list_proposals(status="pending")
        approved = await mgr.list_proposals(status="approved")
        assert len(pending) == 1
        assert pending[0].pr_number == 2
        assert len(approved) == 1


class TestSourceStatus:
    async def test_pause_and_resume(self, mgr: AuditTrailManager) -> None:
        ok = await mgr.set_source_status("boe", "paused", paused_by="op1", paused_reason="mantenimineto")
        assert ok is True
        sources = await mgr.list_sources()
        boe = next(s for s in sources if s.source_id == "boe")
        assert boe.status == "paused"
        assert boe.paused_by == "op1"

        await mgr.set_source_status("boe", "active")
        sources = await mgr.list_sources()
        boe = next(s for s in sources if s.source_id == "boe")
        assert boe.status == "active"

    async def test_unknown_source_returns_false(self, mgr: AuditTrailManager) -> None:
        ok = await mgr.set_source_status("nonexistent", "paused")
        assert ok is False
