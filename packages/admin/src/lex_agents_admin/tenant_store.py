"""Tenant store — CRUD for tenants table (ADR 0060)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS tenants (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    plan       TEXT NOT NULL DEFAULT 'standard',
    disabled   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO tenants (id, name, plan) VALUES ('default', 'Default Tenant', 'enterprise');
"""

_DDL_PG = """
CREATE TABLE IF NOT EXISTS lex_agents_app.tenants (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    plan       TEXT NOT NULL DEFAULT 'standard',
    disabled   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO lex_agents_app.tenants (id, name, plan)
VALUES ('default', 'Default Tenant', 'enterprise')
ON CONFLICT DO NOTHING;
"""


@dataclass
class TenantRecord:
    id: str
    name: str
    plan: str
    disabled: bool
    created_at: str
    updated_at: str


class TenantStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(_DDL_PG)
            logger.info("tenant_store_postgres_mode")
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL_SQLITE)
            await db.commit()
        logger.info("tenant_store_initialized", db_path=self._db_path)

    async def create(self, tenant_id: str, name: str, plan: str = "standard") -> TenantRecord:
        now = datetime.now(UTC)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    "INSERT INTO lex_agents_app.tenants (id, name, plan, created_at, updated_at)"
                    " VALUES ($1,$2,$3,$4,$5)",
                    tenant_id, name, plan, now, now,
                )
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO tenants (id, name, plan, created_at, updated_at)"
                    " VALUES (?,?,?,?,?)",
                    (tenant_id, name, plan, now_s, now_s),
                )
                await db.commit()
        logger.info("tenant_created", tenant_id=tenant_id, plan=plan)
        return TenantRecord(id=tenant_id, name=name, plan=plan, disabled=False,
                            created_at=now_s, updated_at=now_s)

    async def get(self, tenant_id: str) -> TenantRecord | None:
        if is_postgres():
            async with pg_conn() as conn:
                row = await conn.fetchrow(
                    "SELECT id, name, plan, disabled, created_at, updated_at"
                    " FROM lex_agents_app.tenants WHERE id=$1",
                    tenant_id,
                )
            if row is None:
                return None
            return TenantRecord(
                id=row["id"], name=row["name"], plan=row["plan"],
                disabled=bool(row["disabled"]),
                created_at=_fmt_ts(row["created_at"]),
                updated_at=_fmt_ts(row["updated_at"]),
            )
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, name, plan, disabled, created_at, updated_at FROM tenants WHERE id=?",
                (tenant_id,),
            ) as cur:
                row_raw: Any = await cur.fetchone()
        if row_raw is None:
            return None
        return TenantRecord(
            id=row_raw[0], name=row_raw[1], plan=row_raw[2],
            disabled=bool(row_raw[3]),
            created_at=row_raw[4], updated_at=row_raw[5],
        )

    async def list_all(self) -> list[TenantRecord]:
        if is_postgres():
            async with pg_conn() as conn:
                rows = await conn.fetch(
                    "SELECT id, name, plan, disabled, created_at, updated_at"
                    " FROM lex_agents_app.tenants ORDER BY created_at"
                )
            return [
                TenantRecord(
                    id=r["id"], name=r["name"], plan=r["plan"],
                    disabled=bool(r["disabled"]),
                    created_at=_fmt_ts(r["created_at"]),
                    updated_at=_fmt_ts(r["updated_at"]),
                )
                for r in rows
            ]
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, name, plan, disabled, created_at, updated_at"
                " FROM tenants ORDER BY created_at"
            ) as cur:
                rows_raw: list[Any] = list(await cur.fetchall())
        return [
            TenantRecord(
                id=r[0], name=r[1], plan=r[2], disabled=bool(r[3]),
                created_at=r[4], updated_at=r[5],
            )
            for r in rows_raw
        ]

    async def update(self, tenant_id: str, *, name: str | None = None,
                     plan: str | None = None, disabled: bool | None = None) -> bool:
        existing = await self.get(tenant_id)
        if existing is None:
            return False
        now = datetime.now(UTC)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
        new_name = name if name is not None else existing.name
        new_plan = plan if plan is not None else existing.plan
        new_disabled = disabled if disabled is not None else existing.disabled
        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    "UPDATE lex_agents_app.tenants SET name=$1, plan=$2, disabled=$3, updated_at=$4"
                    " WHERE id=$5",
                    new_name, new_plan, new_disabled, now, tenant_id,
                )
            return str(result) != "UPDATE 0"
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "UPDATE tenants SET name=?, plan=?, disabled=?, updated_at=? WHERE id=?",
                (new_name, new_plan, int(new_disabled), now_s, tenant_id),
            ) as cur:
                changed = cur.rowcount
            await db.commit()
        return changed > 0

    async def disable(self, tenant_id: str) -> bool:
        return await self.update(tenant_id, disabled=True)

    async def enable(self, tenant_id: str) -> bool:
        return await self.update(tenant_id, disabled=False)


def _fmt_ts(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return str(v.strftime("%Y-%m-%dT%H:%M:%S"))
    return str(v)
