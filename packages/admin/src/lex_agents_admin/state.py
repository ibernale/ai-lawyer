"""SystemStateManager — kill switches and feature flags (ADR-0032).

Stored in governance.db alongside the audit trail.
In-process TTL cache (5 s) minimises SQLite reads per request.
Kill switch writes invalidate the cache immediately.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_TTL_SECONDS = 5.0

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
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL)
            # Seed global kill switch if absent
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

    async def get_flag(self, key: str, default: Any = None) -> Any:
        cache_key = f"flag:{key}"
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() < cached[1]:
            return cached[0]

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT value FROM feature_flags WHERE key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()

        value = json.loads(row[0]) if row else default
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
            # Cache miss — read from DB
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT engaged FROM kill_switches WHERE target = ?", (t,)
                ) as cur:
                    row = await cur.fetchone()
            engaged = bool(row[0]) if row else False
            self._cache[cache_key] = (engaged, time.monotonic() + _TTL_SECONDS)
            if engaged:
                return True
        return False

    async def get_kill_reason(self, target: str) -> str | None:
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
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        value_str = json.dumps(value)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO feature_flags (key, value, updated_at, updated_by)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value=excluded.value,
                       updated_at=excluded.updated_at,
                       updated_by=excluded.updated_by""",
                (key, value_str, ts, actor),
            )
            await db.commit()
        self._cache.pop(f"flag:{key}", None)
        self._notify("flag.change", {"key": key, "value": value, "actor": actor})
        logger.info("feature_flag_set", key=key, actor=actor)

    async def engage_kill_switch(self, target: str, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reason must not be empty")
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO kill_switches (target, engaged, engaged_at, engaged_by, reason)
                   VALUES (?, 1, ?, ?, ?)
                   ON CONFLICT(target) DO UPDATE SET
                       engaged=1, engaged_at=excluded.engaged_at,
                       engaged_by=excluded.engaged_by, reason=excluded.reason""",
                (target, ts, actor, reason),
            )
            await db.commit()
        # Immediate cache invalidation
        self._cache.pop(f"ks:{target}", None)
        self._cache.pop("ks:global", None)
        self._notify("kill_switch.engage", {"target": target, "actor": actor, "reason": reason})
        logger.warning("kill_switch_engaged", target=target, actor=actor, reason=reason)

    async def release_kill_switch(self, target: str, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("reason must not be empty")
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
