"""In-app notification system — dual-mode: Aurora (asyncpg) or SQLite (aiosqlite).

Notifications are created by:
- SystemStateManager subscribers (kill switch engage/release)
- External webhooks from Grafana / Langfuse (POST /ingest)
- Internal system events
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from lex_agents_shared.db import is_postgres, pg_conn

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# SQLite DDL (local dev only)
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

_SELECT_COLS = "id, source, category, title, body, payload, correlation_id, created_at, read_at, read_by"


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
        if is_postgres():
            logger.info("notification_manager_postgres_mode")
            return
        import aiosqlite
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
        payload_str = _json.dumps(payload) if payload is not None else None
        if is_postgres():
            return await self._pg_create(source, category, title, body, payload_str, correlation_id)
        return await self._sqlite_create(source, category, title, body, payload_str, correlation_id)

    async def list_unread(self, limit: int = 50) -> list[NotificationRow]:
        if is_postgres():
            return await self._pg_list(unread_only=True, limit=limit)
        return await self._sqlite_list(unread_only=True, limit=limit)

    async def list_all(self, limit: int = 100) -> list[NotificationRow]:
        if is_postgres():
            return await self._pg_list(unread_only=False, limit=limit)
        return await self._sqlite_list(unread_only=False, limit=limit)

    async def unread_count(self) -> int:
        if is_postgres():
            async with pg_conn() as conn:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
                )
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def mark_read(self, notification_id: int, read_by: str) -> None:
        ts = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    "UPDATE notifications SET read_at=$1, read_by=$2 WHERE id=$3 AND read_at IS NULL",
                    ts, read_by, notification_id,
                )
            return
        import aiosqlite
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE notifications SET read_at=?, read_by=? WHERE id=? AND read_at IS NULL",
                (ts_str, read_by, notification_id),
            )
            await db.commit()

    async def mark_all_read(self, read_by: str) -> None:
        ts = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    "UPDATE notifications SET read_at=$1, read_by=$2 WHERE read_at IS NULL",
                    ts, read_by,
                )
            return
        import aiosqlite
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE notifications SET read_at=?, read_by=? WHERE read_at IS NULL",
                (ts_str, read_by),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # PostgreSQL
    # ------------------------------------------------------------------

    async def _pg_create(
        self,
        source: str,
        category: str,
        title: str,
        body: str,
        payload_str: str | None,
        correlation_id: str | None,
    ) -> int:
        ts = datetime.now(UTC)
        async with pg_conn() as conn:
            row_id: int = await conn.fetchval(
                """INSERT INTO notifications
                   (source, category, title, body, payload, correlation_id, created_at)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                   RETURNING id""",
                source, category, title, body, payload_str, correlation_id, ts,
            )
        logger.info("notification_created_pg", source=source, category=category, title=title)
        return row_id

    async def _pg_list(self, *, unread_only: bool, limit: int) -> list[NotificationRow]:
        where = "WHERE read_at IS NULL" if unread_only else ""
        async with pg_conn() as conn:
            rows = await conn.fetch(
                f"""SELECT {_SELECT_COLS}
                    FROM notifications {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT $1""",
                limit,
            )
        return [_pg_row_to_notification(r) for r in rows]

    # ------------------------------------------------------------------
    # SQLite
    # ------------------------------------------------------------------

    async def _sqlite_create(
        self,
        source: str,
        category: str,
        title: str,
        body: str,
        payload_str: str | None,
        correlation_id: str | None,
    ) -> int:
        import aiosqlite
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    async def _sqlite_list(self, *, unread_only: bool, limit: int) -> list[NotificationRow]:
        import aiosqlite
        where = "WHERE read_at IS NULL" if unread_only else ""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                f"""SELECT {_SELECT_COLS}
                    FROM notifications {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?""",
                (limit,),
            ) as cur:
                rows = await cur.fetchall()
        return [NotificationRow(*r) for r in rows]


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------

def _pg_row_to_notification(row: Any) -> NotificationRow:
    created = row["created_at"]
    read = row["read_at"]
    return NotificationRow(
        id=row["id"],
        source=row["source"],
        category=row["category"],
        title=row["title"],
        body=row["body"],
        payload=_json.dumps(row["payload"]) if row["payload"] is not None else None,
        correlation_id=row["correlation_id"],
        created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
        read_at=read.isoformat() if read and hasattr(read, "isoformat") else read,
        read_by=row["read_by"],
    )
