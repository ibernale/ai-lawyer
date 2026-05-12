"""Unit tests for SystemStateManager (ADR-0032)."""

from __future__ import annotations

import pytest
from lex_agents_admin.state import SystemStateManager


@pytest.fixture
async def mgr(tmp_path):
    m = SystemStateManager(str(tmp_path / "test.db"))
    await m.init()
    return m


class TestInit:
    async def test_init_creates_tables(self, mgr: SystemStateManager) -> None:
        state = await mgr.get_global_state()
        assert isinstance(state.flags, list)
        assert isinstance(state.kill_switches, list)

    async def test_init_seeds_global_kill_switch(self, mgr: SystemStateManager) -> None:
        state = await mgr.get_global_state()
        targets = [k.target for k in state.kill_switches]
        assert "global" in targets

    async def test_global_kill_switch_starts_released(self, mgr: SystemStateManager) -> None:
        assert not await mgr.is_killed("global")


class TestFeatureFlags:
    async def test_flag_set_get_round_trip(self, mgr: SystemStateManager) -> None:
        await mgr.set_flag("rag.reranker_enabled", True, actor="admin1", reason="test")
        value = await mgr.get_flag("rag.reranker_enabled")
        assert value is True

    async def test_flag_missing_returns_default(self, mgr: SystemStateManager) -> None:
        value = await mgr.get_flag("nonexistent", default=42)
        assert value == 42

    async def test_flag_overwrite(self, mgr: SystemStateManager) -> None:
        await mgr.set_flag("k", "v1", actor="a", reason="r")
        await mgr.set_flag("k", "v2", actor="a", reason="r2")
        assert await mgr.get_flag("k") == "v2"

    async def test_flag_reason_required(self, mgr: SystemStateManager) -> None:
        with pytest.raises(ValueError, match="reason"):
            await mgr.set_flag("k", True, actor="a", reason="   ")


class TestKillSwitch:
    async def test_engage_release(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("global", actor="admin1", reason="incident")
        assert await mgr.is_killed("global")
        await mgr.release_kill_switch("global", actor="admin1", reason="resolved")
        assert not await mgr.is_killed("global")

    async def test_is_killed_global_cascade(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        assert await mgr.is_killed("agent:planner")

    async def test_per_target_kill_switch(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("agent:planner", actor="a", reason="r")
        assert await mgr.is_killed("agent:planner")
        assert not await mgr.is_killed("agent:judge")

    async def test_global_released_per_target_still_killed(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        await mgr.engage_kill_switch("agent:planner", actor="a", reason="r2")
        await mgr.release_kill_switch("global", actor="a", reason="resolved")
        assert await mgr.is_killed("agent:planner")

    async def test_engage_reason_required(self, mgr: SystemStateManager) -> None:
        with pytest.raises(ValueError, match="reason"):
            await mgr.engage_kill_switch("global", actor="a", reason="")

    async def test_get_kill_reason(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("global", actor="a", reason="maintenance window")
        reason = await mgr.get_kill_reason("global")
        assert reason == "maintenance window"

    async def test_reason_cleared_on_release(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        await mgr.release_kill_switch("global", actor="a", reason="done")
        reason = await mgr.get_kill_reason("global")
        assert reason is None


class TestTtlCache:
    async def test_cache_hit_no_reread(self, mgr: SystemStateManager) -> None:
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        # Warm the cache
        assert await mgr.is_killed("global")
        # Directly manipulate DB to simulate external change (cache should still say True)
        import aiosqlite
        async with aiosqlite.connect(mgr._db_path) as db:
            await db.execute(
                "UPDATE kill_switches SET engaged=0 WHERE target='global'"
            )
            await db.commit()
        # Cache hit — should still return True (not re-read DB)
        assert await mgr.is_killed("global")

    async def test_cache_invalidated_on_engage(self, mgr: SystemStateManager) -> None:
        # populate cache with False
        assert not await mgr.is_killed("global")
        # Engage invalidates cache
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        # Should now return True (fresh read)
        assert await mgr.is_killed("global")


class TestSubscribers:
    async def test_subscribe_notified_on_engage(self, mgr: SystemStateManager) -> None:
        events: list[tuple[str, object]] = []
        mgr.subscribe(lambda event, payload: events.append((event, payload)))
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        assert any(e[0] == "kill_switch.engage" for e in events)

    async def test_subscribe_notified_on_release(self, mgr: SystemStateManager) -> None:
        events: list[tuple[str, object]] = []
        mgr.subscribe(lambda event, payload: events.append((event, payload)))
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        await mgr.release_kill_switch("global", actor="a", reason="done")
        assert any(e[0] == "kill_switch.release" for e in events)

    async def test_subscribe_notified_on_flag_change(self, mgr: SystemStateManager) -> None:
        events: list[tuple[str, object]] = []
        mgr.subscribe(lambda event, payload: events.append((event, payload)))
        await mgr.set_flag("k", True, actor="a", reason="r")
        assert any(e[0] == "flag.change" for e in events)

    async def test_subscriber_error_does_not_propagate(self, mgr: SystemStateManager) -> None:
        def bad_cb(event: str, payload: object) -> None:
            raise RuntimeError("boom")

        mgr.subscribe(bad_cb)
        await mgr.engage_kill_switch("global", actor="a", reason="r")
        assert await mgr.is_killed("global")
