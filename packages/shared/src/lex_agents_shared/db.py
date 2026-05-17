"""Database connection factory — asyncpg (Aurora) or aiosqlite (local dev).

Selection logic:
  - DATABASE_URL set → asyncpg pool (PostgreSQL / Aurora Serverless v2)
  - DATABASE_URL not set → aiosqlite (SQLite, local dev / CI)

Usage
-----
    from lex_agents_shared.db import is_postgres, pg_conn

    if is_postgres():
        async with pg_conn() as conn:
            rows = await conn.fetch("SELECT ...")
    else:
        async with aiosqlite.connect(db_path) as db:
            ...

The pool is lazily initialised on first call to `pg_conn()` and can be
explicitly closed with `close_pool()` (e.g. in app shutdown hooks).
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import AsyncIterator

import asyncpg
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Default PostgreSQL schema (backward-compatible with pre-tenancy data)
PG_SCHEMA = "lex_agents_app"

# Tenant schema names must match this pattern after normalization
_SCHEMA_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

_pool: asyncpg.Pool | None = None


# ---------------------------------------------------------------------------
# Tenant schema mapping
# ---------------------------------------------------------------------------

def _tenant_schema(tenant_id: str) -> str:
    """Return the PostgreSQL schema name for the given tenant.

    - tenant_id == "default"  →  "lex_agents_app"  (backward-compatible)
    - any other tenant_id     →  "tenant_<normalized>"
    """
    if tenant_id == "default":
        return PG_SCHEMA
    # Normalise: lowercase, replace non-alnum with _, truncate to 50 chars
    safe = re.sub(r"[^a-z0-9]", "_", tenant_id.lower())[:50]
    schema = f"tenant_{safe}"
    if not _SCHEMA_NAME_RE.match(schema):
        raise ValueError(f"Cannot derive a safe schema name from tenant_id={tenant_id!r}")
    return schema


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

def _resolve_dsn() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Cannot connect to PostgreSQL. "
            "For local dev, leave DATABASE_URL unset to use aiosqlite."
        )
    # Strip SQLAlchemy dialect prefix if present
    return url.replace("postgresql+asyncpg://", "postgresql://")


def is_postgres() -> bool:
    """Return True when DATABASE_URL is set (Aurora / PostgreSQL mode)."""
    return bool(os.environ.get("DATABASE_URL", ""))


async def get_pool(
    *,
    min_size: int = 1,
    max_size: int = 5,
) -> asyncpg.Pool:
    """Return (and lazily create) the shared asyncpg connection pool."""
    global _pool
    if _pool is None:
        dsn = _resolve_dsn()
        logger.info("creating_asyncpg_pool", min_size=min_size, max_size=max_size)
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
        )
        logger.info("asyncpg_pool_ready")
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool (call from app lifespan shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg_pool_closed")


# ---------------------------------------------------------------------------
# Per-request connection helpers
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def pg_conn(tenant_id: str = "default") -> AsyncIterator[asyncpg.Connection]:
    """Async context manager yielding a connection scoped to the tenant's schema.

    Sets ``search_path`` to the tenant schema for the duration of the call,
    then resets to the default schema so the pooled connection is reusable.

    Example::

        async with pg_conn(tenant_id="santander_es") as conn:
            row = await conn.fetchrow("SELECT * FROM consultations WHERE trace_id = $1", tid)
    """
    schema = _tenant_schema(tenant_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"SET search_path TO {schema}, public")
        try:
            yield conn
        finally:
            await conn.execute(f"SET search_path TO {PG_SCHEMA}, public")


@contextlib.asynccontextmanager
async def pg_transaction(tenant_id: str = "default") -> AsyncIterator[asyncpg.Connection]:
    """Async context manager yielding a connection inside an explicit transaction,
    scoped to the tenant's schema.

    The transaction is committed on clean exit and rolled back on exception.

    Example::

        async with pg_transaction(tenant_id="santander_es") as conn:
            await conn.execute("INSERT INTO ...", ...)
            await conn.execute("UPDATE ...", ...)
    """
    schema = _tenant_schema(tenant_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"SET search_path TO {schema}, public")
        try:
            async with conn.transaction():
                yield conn
        finally:
            await conn.execute(f"SET search_path TO {PG_SCHEMA}, public")
