"""Unit tests for NotificationManager."""

from __future__ import annotations

import pytest
from lex_agents_audit.notifications import NotificationManager


@pytest.fixture
async def mgr(tmp_path):
    m = NotificationManager(str(tmp_path / "test.db"))
    await m.init()
    return m


class TestInit:
    async def test_init_creates_table(self, mgr: NotificationManager) -> None:
        rows = await mgr.list_all()
        assert isinstance(rows, list)

    async def test_starts_empty(self, mgr: NotificationManager) -> None:
        assert await mgr.unread_count() == 0


class TestCreate:
    async def test_create_returns_id(self, mgr: NotificationManager) -> None:
        nid = await mgr.create("system", "critical", "Test", "Body")
        assert nid > 0

    async def test_create_increments_unread(self, mgr: NotificationManager) -> None:
        await mgr.create("grafana", "warning", "T1", "B1")
        await mgr.create("grafana", "info", "T2", "B2")
        assert await mgr.unread_count() == 2

    async def test_create_with_payload(self, mgr: NotificationManager) -> None:
        await mgr.create("system", "critical", "T", "B", payload={"target": "global"})
        rows = await mgr.list_all()
        assert rows[0].payload is not None
        assert "global" in rows[0].payload

    async def test_create_with_correlation_id(self, mgr: NotificationManager) -> None:
        await mgr.create("system", "info", "T", "B", correlation_id="abc-123")
        rows = await mgr.list_all()
        assert rows[0].correlation_id == "abc-123"


class TestList:
    async def test_list_all_returns_newest_first(self, mgr: NotificationManager) -> None:
        await mgr.create("system", "info", "First", "B")
        await mgr.create("system", "info", "Second", "B")
        rows = await mgr.list_all()
        assert rows[0].title == "Second"
        assert rows[1].title == "First"

    async def test_list_unread_excludes_read(self, mgr: NotificationManager) -> None:
        nid = await mgr.create("system", "info", "T1", "B")
        await mgr.create("system", "info", "T2", "B")
        await mgr.mark_read(nid, "admin")
        unread = await mgr.list_unread()
        assert len(unread) == 1
        assert unread[0].title == "T2"


class TestMarkRead:
    async def test_mark_read_sets_read_at(self, mgr: NotificationManager) -> None:
        nid = await mgr.create("system", "info", "T", "B")
        await mgr.mark_read(nid, "admin1")
        rows = await mgr.list_all()
        assert rows[0].read_at is not None
        assert rows[0].read_by == "admin1"

    async def test_mark_read_decrements_unread(self, mgr: NotificationManager) -> None:
        nid = await mgr.create("system", "info", "T", "B")
        assert await mgr.unread_count() == 1
        await mgr.mark_read(nid, "admin")
        assert await mgr.unread_count() == 0

    async def test_mark_read_idempotent(self, mgr: NotificationManager) -> None:
        nid = await mgr.create("system", "info", "T", "B")
        await mgr.mark_read(nid, "admin")
        await mgr.mark_read(nid, "admin")  # no error
        assert await mgr.unread_count() == 0

    async def test_mark_all_read(self, mgr: NotificationManager) -> None:
        await mgr.create("system", "info", "T1", "B")
        await mgr.create("grafana", "critical", "T2", "B")
        await mgr.create("dagster", "warning", "T3", "B")
        assert await mgr.unread_count() == 3
        await mgr.mark_all_read("admin")
        assert await mgr.unread_count() == 0
