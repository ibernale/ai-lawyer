"""SystemStateManager — kill switches and feature flags (ADR-0032).

Dual-mode: Aurora (asyncpg, lex_agents_app schema) when DATABASE_URL is set;
aiosqlite (SQLite, local dev) otherwise.

In-process TTL cache (5 s) minimises DB reads per request.
Kill switch writes invalidate the cache immediately.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from lex_agents_shared.db import is_postgres, pg_conn, pg_transaction

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_TTL_SECONDS = 5.0

# SQLite DDL (local dev only — PostgreSQL DDL lives in Alembic migration 0001)
_DDL = """
CREATE TABLE IF NOT EXISTS feature_flags (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME NOT NULL,
    updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switches (
    target TEXT PRIMARY KEY,
    engaged INTEGER NOT NULL DEFAULT 0,
    engaged_at DATETIME,
    engaged_by TEXT,
    reason TEXT
);
"""

_KILL_SWITCH_SEED = [("global",)]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FlagRow:
    key: str
    value: str
    updated_at: str
    updated_by: str


@dataclass
class KillSwitchRow:
    target: str
    engaged: bool
    engaged_at: str | None
    engaged_by: str | None
    reason: str | None


@dataclass
class GlobalState:
    flags: list[FlagRow]
    kill_switches: list[KillSwitchRow]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: SystemStateManager | None = None


def get_system_state_manager() -> SystemStateManager | None:
    return _manager


def set_system_state_manager(m: SystemStateManager) -> None:
    global _manager
    _manager = m


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SystemStateManager:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._cache: dict[str, tuple[Any, float]] = {}
        self._subscribers: list[Callable[[str, Any], None]] = []

    async def init(self) -> None:
        if is_postgres():
            await self._pg_seed_kill_switches()
            logger.info("system_state_postgres_mode")
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL)
            for (target,) in _KILL_SWITCH_SEED:
                await db.execute(
                    "INSERT OR IGNORE INTO kill_switches (target, engaged) VALUES (?, 0)",
                    (target,),
                )
            await db.commit()
        logger.info("system_state_initialized", db_path=self._db_path)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_global_state(self) -> GlobalState:
        if is_postgres():
            return await self._pg_get_global_state()
        return await self._sqlite_get_global_state()

    async def get_flag(self, key: str, default: Any = None) -> Any:
        cache_key = f"flag:{key}"
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() < cached[1]:
            return cached[0]

        if is_postgres():
            value = await self._pg_get_flag(key, default)
        else:
            value = await self._sqlite_get_flag(key, default)

        self._cache[cache_key] = (value, time.monotonic() + _TTL_SECONDS)
        return value

    async def is_killed(self, target: str) -> bool:
        """True if global kill switch OR this specific target is engaged."""
        targets = {"global", target} if target != "global" else {"global"}
        for t in targets:
            cache_key = f"ks:{t}"
            cached = self._cache.get(cache_key)
            if cached and time.monotonic() < cached[1]:
                if cached[0]:
                    return True
                continue
            if is_postgres():
                engaged = await self._pg_is_engaged(t)
            else:
                engaged = await self._sqlite_is_engaged(t)
            self._cache[cache_key] = (engaged, time.monotonic() + _TTL_SECONDS)
            if engaged:
                return True
        return False

    async def get_kill_reason(self, target: str) -> str | None:
        if is_postgres():
            async with pg_conn() as conn:
                row = await conn.fetchrow(
                    "SELECT reason FROM kill_switches WHERE target = $1", target
                )
            return row["reason"] if row else None
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT reason FROM kill_switches WHERE target = ?", (target,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def set_flag(self, key: str, value: Any, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reason must not be empty")
        ts = datetime.now(UTC)
        value_str = json.dumps(value)

        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    """INSERT INTO feature_flags (key, value, updated_at, updated_by)
                       VALUES ($1, $2::jsonb, $3, $4)
                       ON CONFLICT (key) DO UPDATE
                           SET value=$2::jsonb, updated_at=$3, updated_by=$4""",
                    key, value_str, ts, actor,
                )
        else:
            import aiosqlite
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S")
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO feature_flags (key, value, updated_at, updated_by)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                           value=excluded.value,
                           updated_at=excluded.updated_at,
                           updated_by=excluded.updated_by""",
                    (key, value_str, ts_str, actor),
                )
                await db.commit()

        self._cache.pop(f"flag:{key}", None)
        self._notify("flag.change", {"key": key, "value": value, "actor": actor})
        logger.info("feature_flag_set", key=key, actor=actor)

    async def engage_kill_switch(self, target: str, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reason must not be empty")
        ts = datetime.now(UTC)

        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    """INSERT INTO kill_switches (target, engaged, engaged_at, actor, reason)
                       VALUES ($1, true, $2, $3, $4)
                       ON CONFLICT (target) DO UPDATE
                           SET engaged=true, engaged_at=$2, actor=$3, reason=$4""",
                    target, ts, actor, reason,
                )
        else:
            import aiosqlite
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S")
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO kill_switches (target, engaged, engaged_at, engaged_by, reason)
                       VALUES (?, 1, ?, ?, ?)
                       ON CONFLICT(target) DO UPDATE SET
                           engaged=1, engaged_at=excluded.engaged_at,
                           engaged_by=excluded.engaged_by, reason=excluded.reason""",
                    (target, ts.strftime("%Y-%m-%dT%H:%M:%S"), actor, reason),
                )
                await db.commit()

        self._cache.pop(f"ks:{target}", None)
        self._cache.pop("ks:global", None)
        self._notify("kill_switch.engage", {"target": target, "actor": actor, "reason": reason})
        logger.warning("kill_switch_engaged", target=target, actor=actor, reason=reason)

    async def release_kill_switch(self, target: str, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reason must not be empty")

        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    "UPDATE kill_switches SET engaged=false, engaged_at=NULL, actor=NULL, reason=NULL WHERE target=$1",
                    target,
                )
            if result == "UPDATE 0":
                raise ValueError(f"unknown kill switch target: {target!r}")
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                cur = await db.execute(
                    "UPDATE kill_switches SET engaged=0, engaged_at=NULL, engaged_by=NULL, reason=NULL WHERE target=?",
                    (target,),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"unknown kill switch target: {target!r}")
                await db.commit()

        self._cache.pop(f"ks:{target}", None)
        self._cache.pop("ks:global", None)
        self._notify("kill_switch.release", {"target": target, "actor": actor, "reason": reason})
        logger.info("kill_switch_released", target=target, actor=actor)

    # ------------------------------------------------------------------
    # PostgreSQL helpers
    # ------------------------------------------------------------------

    async def _pg_seed_kill_switches(self) -> None:
        async with pg_conn() as conn:
            for (target,) in _KILL_SWITCH_SEED:
                await conn.execute(
                    "INSERT INTO kill_switches (target, engaged) VALUES ($1, false) ON CONFLICT (target) DO NOTHING",
                    target,
                )

    async def _pg_get_global_state(self) -> GlobalState:
        async with pg_conn() as conn:
            flag_rows = await conn.fetch(
                "SELECT key, value, updated_at, updated_by FROM feature_flags ORDER BY key"
            )
            ks_rows = await conn.fetch(
                "SELECT target, engaged, engaged_at, actor, reason FROM kill_switches ORDER BY target"
            )
        flags = [
            FlagRow(
                key=r["key"],
                value=json.dumps(r["value"]) if not isinstance(r["value"], str) else r["value"],
                updated_at=r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else str(r["updated_at"]),
                updated_by=r["updated_by"],
            )
            for r in flag_rows
        ]
        kill_switches = [
            KillSwitchRow(
                target=r["target"],
                engaged=bool(r["engaged"]),
                engaged_at=r["engaged_at"].isoformat() if r["engaged_at"] and hasattr(r["engaged_at"], "isoformat") else r["engaged_at"],
                engaged_by=r["actor"],
                reason=r["reason"],
            )
            for r in ks_rows
        ]
        return GlobalState(flags=flags, kill_switches=kill_switches)

    async def _pg_get_flag(self, key: str, default: Any) -> Any:
        async with pg_conn() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM feature_flags WHERE key = $1", key
            )
        if row is None:
            return default
        val = row["value"]
        # asyncpg returns JSONB as a Python object already
        return val if not isinstance(val, str) else json.loads(val)

    async def _pg_is_engaged(self, target: str) -> bool:
        async with pg_conn() as conn:
            row = await conn.fetchrow(
                "SELECT engaged FROM kill_switches WHERE target = $1", target
            )
        return bool(row["engaged"]) if row else False

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    async def _sqlite_get_global_state(self) -> GlobalState:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT key, value, updated_at, updated_by FROM feature_flags ORDER BY key"
            ) as cur:
                flag_rows = await cur.fetchall()
            async with db.execute(
                "SELECT target, engaged, engaged_at, engaged_by, reason FROM kill_switches ORDER BY target"
            ) as cur:
                ks_rows = await cur.fetchall()
        flags = [FlagRow(*r) for r in flag_rows]
        kill_switches = [
            KillSwitchRow(r[0], bool(r[1]), r[2], r[3], r[4]) for r in ks_rows
        ]
        return GlobalState(flags=flags, kill_switches=kill_switches)

    async def _sqlite_get_flag(self, key: str, default: Any) -> Any:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT value FROM feature_flags WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
        return json.loads(row[0]) if row else default

    async def _sqlite_is_engaged(self, target: str) -> bool:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT engaged FROM kill_switches WHERE target = ?", (target,)
            ) as cur:
                row = await cur.fetchone()
        return bool(row[0]) if row else False

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        self._subscribers.append(callback)

    def _notify(self, event: str, payload: Any) -> None:
        for cb in self._subscribers:
            try:
                cb(event, payload)
            except Exception as exc:
                logger.warning("subscriber_error", evt=event, error=str(exc))
