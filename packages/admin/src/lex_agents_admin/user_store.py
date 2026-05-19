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

_DDL_SQLITE_BASE = """
CREATE TABLE IF NOT EXISTS admin_users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'analyst',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0
);
"""

# Additive migrations — applied one at a time; errors for "duplicate column name"
# or "table already exists" are silently ignored so startup is idempotent on both
# fresh and pre-existing DBs (ALTER TABLE ... ADD COLUMN IF NOT EXISTS not supported
# in SQLite).
_MIGRATIONS_SQLITE = [
    "ALTER TABLE admin_users ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'",
    "ALTER TABLE admin_users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1",
    "CREATE INDEX IF NOT EXISTS idx_admin_users_tenant ON admin_users(tenant_id)",
    """CREATE TABLE IF NOT EXISTS revoked_jtis (
        jti        TEXT PRIMARY KEY,
        revoked_at TEXT NOT NULL DEFAULT (datetime('now')),
        reason     TEXT
    )""",
]


@dataclass
class UserRecord:
    username: str
    password_hash: str
    role: str
    created_at: str
    updated_at: str
    disabled: bool
    tenant_id: str = "default"
    token_version: int = 1


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
                # Additive column migrations — IF NOT EXISTS is idempotent in PG 9.6+
                await conn.execute(
                    "ALTER TABLE lex_agents_app.admin_users"
                    " ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'"
                )
                await conn.execute(
                    "ALTER TABLE lex_agents_app.admin_users"
                    " ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 1"
                )
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS lex_agents_app.revoked_jtis ("
                    "  jti TEXT PRIMARY KEY,"
                    "  revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                    "  reason TEXT"
                    ")"
                )
                rows = await conn.fetch(
                    "SELECT username, password_hash, role, created_at, updated_at,"
                    " disabled, tenant_id, token_version"
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
                    tenant_id=r["tenant_id"] or "default",
                    token_version=int(r["token_version"] or 1),
                )
            logger.info("user_store_postgres_mode", count=len(self._cache))
            return

        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL_SQLITE_BASE)
            for stmt in _MIGRATIONS_SQLITE:
                try:
                    await db.execute(stmt)
                except Exception:  # noqa: S110 — duplicate column / index already exists
                    pass
            await db.commit()
            async with db.execute(
                "SELECT username, password_hash, role, created_at, updated_at,"
                " disabled, tenant_id, token_version"
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
                tenant_id=r[6] if r[6] else "default",
                token_version=int(r[7]) if r[7] is not None else 1,
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

    def get_by_tenant_sync(self, tenant_id: str) -> list[UserRecord]:
        """Return all non-disabled users for a tenant (sync, from cache)."""
        return [u for u in self._cache.values() if u.tenant_id == tenant_id]

    async def get_by_tenant(self, tenant_id: str) -> list[UserRecord]:
        return self.get_by_tenant_sync(tenant_id)

    async def create(
        self,
        username: str,
        password_hash: str,
        role: str,
        tenant_id: str = "default",
    ) -> bool:
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
                           (username, password_hash, role, created_at, updated_at,
                            disabled, tenant_id, token_version)
                           VALUES ($1, $2, $3, $4, $5, FALSE, $6, 1)""",
                        username, password_hash, role, now, now, tenant_id,
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
                           (username, password_hash, role, created_at, updated_at,
                            disabled, tenant_id, token_version)
                           VALUES (?, ?, ?, ?, ?, 0, ?, 1)""",
                        (username, password_hash, role, now_s, now_s, tenant_id),
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
            tenant_id=tenant_id,
            token_version=1,
        )
        logger.info("user_created", username=username, role=role, tenant_id=tenant_id)
        return True

    async def update(
        self,
        username: str,
        *,
        role: str | None = None,
        password_hash: str | None = None,
        disabled: bool | None = None,
        token_version_bump: bool = False,
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
        new_token_version = existing.token_version + 1 if token_version_bump else existing.token_version

        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    """UPDATE lex_agents_app.admin_users
                       SET role=$1, password_hash=$2, disabled=$3, updated_at=$4,
                           token_version=$5
                       WHERE username=$6""",
                    new_role, new_hash, new_disabled, now, new_token_version, username,
                )
            if str(result) == "UPDATE 0":
                return False
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    """UPDATE admin_users
                       SET role=?, password_hash=?, disabled=?, updated_at=?,
                           token_version=?
                       WHERE username=?""",
                    (new_role, new_hash, int(new_disabled), now_s,
                     new_token_version, username),
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
            tenant_id=existing.tenant_id,
            token_version=new_token_version,
        )
        logger.info("user_updated", username=username, token_version_bumped=token_version_bump)
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
        return str(v.strftime("%Y-%m-%dT%H:%M:%S"))
    return str(v)
