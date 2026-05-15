"""User store — DB-backed user management (ADR 0057 / admin panel).

Dual-mode: Aurora (asyncpg) when DATABASE_URL set; aiosqlite otherwise.
Maintains an in-memory sync cache so _load_users() can read without await.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn

logger = structlog.get_logger(__name__)

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS admin_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'analyst',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class UserRecord:
    username: str
    password_hash: str
    role: str
    created_at: str
    updated_at: str
    disabled: bool


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: UserStore | None = None


def get_user_store() -> UserStore | None:
    return _store


def set_user_store(s: UserStore) -> None:
    global _store
    _store = s


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class UserStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._cache: dict[str, UserRecord] = {}

    async def init(self) -> None:
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS lex_agents_app.admin_users (
                        username      TEXT PRIMARY KEY,
                        password_hash TEXT NOT NULL,
                        role          TEXT NOT NULL DEFAULT 'analyst',
                        created_at    TIMESTAMPTZ NOT NULL,
                        updated_at    TIMESTAMPTZ NOT NULL,
                        disabled      BOOLEAN NOT NULL DEFAULT FALSE
                    )
                """)
                rows = await conn.fetch(
                    "SELECT username, password_hash, role, created_at, updated_at, disabled"
                    " FROM lex_agents_app.admin_users"
                )
            for r in rows:
                self._cache[r["username"]] = UserRecord(
                    username=r["username"],
                    password_hash=r["password_hash"],
                    role=r["role"],
                    created_at=_fmt_ts(r["created_at"]),
                    updated_at=_fmt_ts(r["updated_at"]),
                    disabled=bool(r["disabled"]),
                )
            logger.info("user_store_postgres_mode", count=len(self._cache))
            return

        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL_SQLITE)
            await db.commit()
            async with db.execute(
                "SELECT username, password_hash, role, created_at, updated_at, disabled"
                " FROM admin_users"
            ) as cur:
                rows_raw: list[Any] = list(await cur.fetchall())

        for r in rows_raw:
            self._cache[r[0]] = UserRecord(
                username=r[0],
                password_hash=r[1],
                role=r[2],
                created_at=r[3],
                updated_at=r[4],
                disabled=bool(r[5]),
            )
        logger.info("user_store_initialized", db_path=self._db_path, count=len(self._cache))

    # ------------------------------------------------------------------
    # Sync cache read — used by auth._load_users() without await
    # ------------------------------------------------------------------

    def get_all_sync(self) -> list[UserRecord]:
        """Return all users from the in-memory cache (sync, no await needed)."""
        return list(self._cache.values())

    # ------------------------------------------------------------------
    # Async reads
    # ------------------------------------------------------------------

    async def get_all(self) -> list[UserRecord]:
        return list(self._cache.values())

    async def get_by_username(self, username: str) -> UserRecord | None:
        return self._cache.get(username)

    # ------------------------------------------------------------------
    # Writes (DB + cache)
    # ------------------------------------------------------------------

    async def create(self, username: str, password_hash: str, role: str) -> bool:
        """Insert a new user. Returns False if username already exists."""
        if username in self._cache:
            return False

        now = datetime.now(UTC)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")

        if is_postgres():
            async with pg_conn() as conn:
                try:
                    await conn.execute(
                        """INSERT INTO lex_agents_app.admin_users
                           (username, password_hash, role, created_at, updated_at, disabled)
                           VALUES ($1, $2, $3, $4, $5, FALSE)""",
                        username, password_hash, role, now, now,
                    )
                except Exception as exc:
                    if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                        return False
                    raise
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                try:
                    await db.execute(
                        """INSERT INTO admin_users
                           (username, password_hash, role, created_at, updated_at, disabled)
                           VALUES (?, ?, ?, ?, ?, 0)""",
                        (username, password_hash, role, now_s, now_s),
                    )
                    await db.commit()
                except Exception as exc:
                    if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                        return False
                    raise

        self._cache[username] = UserRecord(
            username=username,
            password_hash=password_hash,
            role=role,
            created_at=now_s,
            updated_at=now_s,
            disabled=False,
        )
        logger.info("user_created", username=username, role=role)
        return True

    async def update(
        self,
        username: str,
        *,
        role: str | None = None,
        password_hash: str | None = None,
        disabled: bool | None = None,
    ) -> bool:
        """Update one or more fields. Returns False if user not found."""
        existing = self._cache.get(username)
        if existing is None:
            return False

        now = datetime.now(UTC)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")

        new_role = role if role is not None else existing.role
        new_hash = password_hash if password_hash is not None else existing.password_hash
        new_disabled = disabled if disabled is not None else existing.disabled

        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    """UPDATE lex_agents_app.admin_users
                       SET role=$1, password_hash=$2, disabled=$3, updated_at=$4
                       WHERE username=$5""",
                    new_role, new_hash, new_disabled, now, username,
                )
            if str(result) == "UPDATE 0":
                return False
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    """UPDATE admin_users
                       SET role=?, password_hash=?, disabled=?, updated_at=?
                       WHERE username=?""",
                    (new_role, new_hash, int(new_disabled), now_s, username),
                ) as cur:
                    changed = cur.rowcount
                await db.commit()
            if changed == 0:
                return False

        self._cache[username] = UserRecord(
            username=username,
            password_hash=new_hash,
            role=new_role,
            created_at=existing.created_at,
            updated_at=now_s,
            disabled=new_disabled,
        )
        logger.info("user_updated", username=username)
        return True

    async def delete(self, username: str) -> bool:
        """Delete a user permanently. Returns False if not found."""
        if username not in self._cache:
            return False

        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    "DELETE FROM lex_agents_app.admin_users WHERE username=$1",
                    username,
                )
            if str(result) == "DELETE 0":
                return False
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "DELETE FROM admin_users WHERE username=?",
                    (username,),
                ) as cur:
                    changed = cur.rowcount
                await db.commit()
            if changed == 0:
                return False

        del self._cache[username]
        logger.info("user_deleted", username=username)
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    return str(v)
