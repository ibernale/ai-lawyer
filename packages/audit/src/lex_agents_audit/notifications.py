"""In-app notification system — stored in governance.db alongside audit trail.

Notifications are created by:
- SystemStateManager subscribers (kill switch engage/release)
- External webhooks from Grafana / Langfuse / Dagster (POST /ingest)
- Internal system events
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS notifications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    body           TEXT    NOT NULL,
    payload        TEXT,
    correlation_id TEXT,
    created_at     DATETIME NOT NULL,
    read_at        DATETIME,
    read_by        TEXT
);
"""

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class NotificationRow:
    id: int
    source: str
    category: str
    title: str
    body: str
    payload: str | None
    correlation_id: str | None
    created_at: str
    read_at: str | None
    read_by: str | None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: NotificationManager | None = None


def get_notification_manager() -> NotificationManager | None:
    return _manager


def set_notification_manager(m: NotificationManager | None) -> None:
    global _manager
    _manager = m


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class NotificationManager:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL)
            await db.commit()
        logger.info("notification_manager_initialized", db_path=self._db_path)

    async def create(
        self,
        source: str,
        category: str,
        title: str,
        body: str,
        *,
        payload: Any = None,
        correlation_id: str | None = None,
    ) -> int:
        import json as _json

        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload_str = _json.dumps(payload) if payload is not None else None
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                """INSERT INTO notifications
                   (source, category, title, body, payload, correlation_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source, category, title, body, payload_str, correlation_id, ts),
            )
            await db.commit()
            row_id = cur.lastrowid or 0
        logger.info("notification_created", source=source, category=category, title=title)
        return row_id

    async def list_unread(self, limit: int = 50) -> list[NotificationRow]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """SELECT id, source, category, title, body, payload,
                          correlation_id, created_at, read_at, read_by
                   FROM notifications
                   WHERE read_at IS NULL
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [NotificationRow(*r) for r in rows]

    async def list_all(self, limit: int = 100) -> list[NotificationRow]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """SELECT id, source, category, title, body, payload,
                          correlation_id, created_at, read_at, read_by
                   FROM notifications
                   ORDER BY created_at DESC, id DESC
                   LIMIT ?""",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [NotificationRow(*r) for r in rows]

    async def unread_count(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def mark_read(self, notification_id: int, read_by: str) -> None:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE notifications SET read_at=?, read_by=? WHERE id=? AND read_at IS NULL",
                (ts, read_by, notification_id),
            )
            await db.commit()

    async def mark_all_read(self, read_by: str) -> None:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE notifications SET read_at=?, read_by=? WHERE read_at IS NULL",
                (ts, read_by),
            )
            await db.commit()
