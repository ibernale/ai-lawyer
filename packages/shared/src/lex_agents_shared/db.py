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
from collections.abc import AsyncIterator

import asyncpg
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# PostgreSQL schema that holds all application tables (mirrors Alembic migration)
PG_SCHEMA = "lex_agents_app"

_pool: asyncpg.Pool | None = None


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
            # Ensure every connection works in the application schema
            init=_set_search_path,
        )
        logger.info("asyncpg_pool_ready")
    return _pool


async def _set_search_path(conn: asyncpg.Connection) -> None:
    """Run after each new connection is opened in the pool."""
    await conn.execute(f"SET search_path TO {PG_SCHEMA}, public")


async def close_pool() -> None:
    """Gracefully close the pool (call from app lifespan shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg_pool_closed")


@contextlib.asynccontextmanager
async def pg_conn() -> AsyncIterator[asyncpg.Connection]:
    """Async context manager that yields a single connection from the pool.

    Example::

        async with pg_conn() as conn:
            row = await conn.fetchrow("SELECT * FROM feature_flags WHERE key = $1", key)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn

@contextlib.asynccontextmanager
async def pg_transaction() -> AsyncIterator[asyncpg.Connection]:
    """Async context manager that yields a connection inside an explicit transaction.

    The transaction is committed on clean exit and rolled back on exception.

    Example::

        async with pg_transaction() as conn:
            await conn.execute("INSERT INTO ...", ...)
            await conn.execute("UPDATE ...", ...)
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
