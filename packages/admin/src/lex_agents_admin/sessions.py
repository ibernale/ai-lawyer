"""Session store — Cognito-compatible adapter (ADR 0057).

Dual-mode: Aurora (asyncpg) when DATABASE_URL is set; aiosqlite otherwise.
Designed as an adapter: swap the implementation for Cognito API in Fase 10.1
without changing endpoints or frontend.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DEFAULT_TTL_HOURS = 8

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    role         TEXT NOT NULL,
    ip_address   TEXT NOT NULL DEFAULT '',
    user_agent   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    revoked_at   TEXT,
    revoked_by   TEXT
);
CREATE INDEX IF NOT EXISTS sessions_username ON sessions (username);
CREATE INDEX IF NOT EXISTS sessions_expires ON sessions (expires_at);
"""


@dataclass
class SessionRow:
    id: str
    username: str
    role: str
    ip_address: str
    user_agent: str
    created_at: str
    last_used_at: str
    expires_at: str
    revoked_at: str | None
    revoked_by: str | None
    suspicious: bool


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: SessionManager | None = None


def get_session_manager() -> SessionManager | None:
    return _manager


def set_session_manager(m: SessionManager) -> None:
    global _manager
    _manager = m


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

_REVOKE_CACHE_TTL = 5.0  # seconds — tolerable lag before revocation propagates


class SessionManager:
    def __init__(self, db_path: str, ttl_hours: int = _DEFAULT_TTL_HOURS) -> None:
        self._db_path = db_path
        self._ttl_hours = ttl_hours
        self._revoke_cache: dict[str, tuple[bool, float]] = {}

    async def init(self) -> None:
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS lex_agents_app.sessions (
                        id           TEXT PRIMARY KEY,
                        username     TEXT NOT NULL,
                        role         TEXT NOT NULL,
                        ip_address   TEXT NOT NULL DEFAULT '',
                        user_agent   TEXT NOT NULL DEFAULT '',
                        created_at   TIMESTAMPTZ NOT NULL,
                        last_used_at TIMESTAMPTZ NOT NULL,
                        expires_at   TIMESTAMPTZ NOT NULL,
                        revoked_at   TIMESTAMPTZ,
                        revoked_by   TEXT
                    )
                """)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS sessions_username ON lex_agents_app.sessions (username)"
                )
            logger.info("session_manager_postgres_mode")
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL_SQLITE)
            await db.commit()
        logger.info("session_manager_initialized", db_path=self._db_path)

    async def create(
        self,
        username: str,
        role: str,
        ip: str,
        user_agent: str,
    ) -> str:
        now = datetime.now(UTC)
        expires = now + timedelta(hours=self._ttl_hours)
        session_id = str(uuid.uuid4())
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
        exp_s = expires.strftime("%Y-%m-%dT%H:%M:%S")

        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    """INSERT INTO lex_agents_app.sessions
                       (id, username, role, ip_address, user_agent,
                        created_at, last_used_at, expires_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    session_id, username, role, ip, user_agent, now, now, expires,
                )
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO sessions
                       (id, username, role, ip_address, user_agent,
                        created_at, last_used_at, expires_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (session_id, username, role, ip, user_agent, now_s, now_s, exp_s),
                )
                await db.commit()
        logger.info("session_created", session_id=session_id, username=username)
        return session_id

    async def is_revoked(self, session_id: str) -> bool:
        """Return True if session is unknown, explicitly revoked, or expired.

        Result is cached for up to _REVOKE_CACHE_TTL seconds to avoid a DB
        round-trip on every authenticated request. revoke() writes True into
        the cache immediately so the check is fail-closed on revocation.
        """
        now = time.monotonic()
        cached = self._revoke_cache.get(session_id)
        if cached is not None:
            result, ts = cached
            if now - ts < _REVOKE_CACHE_TTL:
                return result

        result = await self._check_revoked(session_id)
        self._revoke_cache[session_id] = (result, now)
        return result

    async def _check_revoked(self, session_id: str) -> bool:
        """DB-level revocation check (uncached)."""
        if is_postgres():
            async with pg_conn() as conn:
                row = await conn.fetchrow(
                    "SELECT revoked_at, expires_at FROM lex_agents_app.sessions WHERE id=$1",
                    session_id,
                )
            if row is None:
                return True
            if row["revoked_at"] is not None:
                return True
            exp = row["expires_at"]
            return exp.replace(tzinfo=UTC) < datetime.now(UTC) if exp else True
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT revoked_at, expires_at FROM sessions WHERE id=?",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return True
        revoked_at, expires_at = row
        if revoked_at is not None:
            return True
        now_s = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        return (expires_at or "") < now_s

    async def update_last_used(self, session_id: str, ip: str) -> None:
        now = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    "UPDATE lex_agents_app.sessions SET last_used_at=$1, ip_address=$2 WHERE id=$3",
                    now, ip, session_id,
                )
        else:
            now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "UPDATE sessions SET last_used_at=?, ip_address=? WHERE id=?",
                    (now_s, ip, session_id),
                )
                await db.commit()

    async def revoke(self, session_id: str, revoked_by: str) -> bool:
        now = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    """UPDATE lex_agents_app.sessions
                       SET revoked_at=$1, revoked_by=$2
                       WHERE id=$3 AND revoked_at IS NULL""",
                    now, revoked_by, session_id,
                )
            ok = str(result) != "UPDATE 0"
        else:
            now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "UPDATE sessions SET revoked_at=?, revoked_by=? WHERE id=? AND revoked_at IS NULL",
                    (now_s, revoked_by, session_id),
                ) as cur:
                    changed = cur.rowcount
                await db.commit()
            ok = changed > 0
        if ok:
            # Propagate to cache immediately so subsequent is_revoked() calls
            # return True without waiting for _REVOKE_CACHE_TTL to expire.
            self._revoke_cache[session_id] = (True, time.monotonic())
        return ok

    async def revoke_all(
        self,
        username: str,
        *,
        except_session_id: str | None = None,
        revoked_by: str,
    ) -> int:
        now = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                if except_session_id:
                    result = await conn.execute(
                        """UPDATE lex_agents_app.sessions
                           SET revoked_at=$1, revoked_by=$2
                           WHERE username=$3 AND id!=$4 AND revoked_at IS NULL""",
                        now, revoked_by, username, except_session_id,
                    )
                else:
                    result = await conn.execute(
                        """UPDATE lex_agents_app.sessions
                           SET revoked_at=$1, revoked_by=$2
                           WHERE username=$3 AND revoked_at IS NULL""",
                        now, revoked_by, username,
                    )
            parts = str(result).split()
            return int(parts[-1]) if parts else 0
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            if except_session_id:
                async with db.execute(
                    "UPDATE sessions SET revoked_at=?, revoked_by=? WHERE username=? AND id!=? AND revoked_at IS NULL",
                    (now_s, revoked_by, username, except_session_id),
                ) as cur:
                    changed = cur.rowcount
            else:
                async with db.execute(
                    "UPDATE sessions SET revoked_at=?, revoked_by=? WHERE username=? AND revoked_at IS NULL",
                    (now_s, revoked_by, username),
                ) as cur:
                    changed = cur.rowcount
            await db.commit()
        return changed

    async def get_active(self, username: str) -> list[SessionRow]:
        now_s = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        if is_postgres():
            async with pg_conn() as conn:
                rows = await conn.fetch(
                    """SELECT id, username, role, ip_address, user_agent,
                              created_at, last_used_at, expires_at, revoked_at, revoked_by
                       FROM lex_agents_app.sessions
                       WHERE username=$1 AND revoked_at IS NULL AND expires_at > $2
                       ORDER BY last_used_at DESC""",
                    username, datetime.now(UTC),
                )
            result = []
            all_ips = [r["ip_address"] for r in rows]
            for r in rows:
                result.append(SessionRow(
                    id=r["id"], username=r["username"], role=r["role"],
                    ip_address=r["ip_address"], user_agent=r["user_agent"],
                    created_at=_fmt_ts(r["created_at"]),
                    last_used_at=_fmt_ts(r["last_used_at"]),
                    expires_at=_fmt_ts(r["expires_at"]),
                    revoked_at=_fmt_ts(r["revoked_at"]) if r["revoked_at"] else None,
                    revoked_by=r["revoked_by"],
                    suspicious=_is_suspicious(r["ip_address"], all_ips),
                ))
            return result
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """SELECT id, username, role, ip_address, user_agent,
                          created_at, last_used_at, expires_at, revoked_at, revoked_by
                   FROM sessions
                   WHERE username=? AND revoked_at IS NULL AND expires_at > ?
                   ORDER BY last_used_at DESC""",
                (username, now_s),
            ) as cur:
                rows_raw: list[Any] = list(await cur.fetchall())
        all_ips = [r[3] for r in rows_raw]
        return [
            SessionRow(
                id=r[0], username=r[1], role=r[2], ip_address=r[3], user_agent=r[4],
                created_at=r[5], last_used_at=r[6], expires_at=r[7],
                revoked_at=r[8], revoked_by=r[9],
                suspicious=_is_suspicious(r[3], all_ips),
            )
            for r in rows_raw
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    return str(v)


def _is_suspicious(ip: str, all_ips: list[str]) -> bool:
    """Flag if the IP /24 prefix differs from all other recent sessions."""
    def prefix(addr: str) -> str:
        parts = addr.split(".")
        return ".".join(parts[:3]) if len(parts) == 4 else addr

    my_prefix = prefix(ip)
    others = [prefix(a) for a in all_ips if a != ip][:3]
    return bool(others) and all(p != my_prefix for p in others)
