"""User audit log store — GDPR/DORA 7-year retention (ADR 0060).

Distinct from lex_agents_audit (LLM response audit). This store tracks
identity and access management events: user created/disabled, invitation
sent/accepted/revoked, session revoked, tenant created/disabled.

PII note: email addresses are stored in the detail JSON blob only, never
in the top-level columns that structlog would emit. The purge_after column
marks rows eligible for scheduled deletion after 7 years.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Canonical action identifiers
ACTION_USER_CREATED = "user.created"
ACTION_USER_DISABLED = "user.disabled"
ACTION_USER_ENABLED = "user.enabled"
ACTION_USER_ROLE_CHANGED = "user.role_changed"
ACTION_USER_PW_RESET = "user.password_reset"
ACTION_USER_FORCE_RELOGIN = "user.force_relogin"
ACTION_INVITATION_SENT = "invitation.sent"
ACTION_INVITATION_ACCEPTED = "invitation.accepted"
ACTION_INVITATION_REVOKED = "invitation.revoked"
ACTION_TENANT_CREATED = "tenant.created"
ACTION_TENANT_DISABLED = "tenant.disabled"
ACTION_TENANT_ENABLED = "tenant.enabled"
ACTION_SESSION_REVOKED = "session.revoked"

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS user_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    ip_address  TEXT,
    detail      TEXT,
    purge_after TEXT NOT NULL DEFAULT (datetime('now', '+7 years')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_date ON user_audit_log(tenant_id, created_at);
"""

_DDL_PG = """
CREATE TABLE IF NOT EXISTS lex_agents_app.user_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    ip_address  TEXT,
    detail      TEXT,
    purge_after TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 years'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_date
    ON lex_agents_app.user_audit_log(tenant_id, created_at);
"""


@dataclass
class AuditEntry:
    id: int
    tenant_id: str
    actor: str
    action: str
    target: str | None
    ip_address: str | None
    detail: dict[str, Any] | None
    created_at: str


class UserAuditStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(_DDL_PG)
            logger.info("user_audit_store_postgres_mode")
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL_SQLITE)
            await db.commit()
        logger.info("user_audit_store_initialized", db_path=self._db_path)

    async def log(
        self,
        tenant_id: str,
        actor: str,
        action: str,
        *,
        target: str | None = None,
        ip: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        detail_json = json.dumps(detail) if detail else None
        now = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    "INSERT INTO lex_agents_app.user_audit_log"
                    " (tenant_id, actor, action, target, ip_address, detail, created_at)"
                    " VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    tenant_id, actor, action, target, ip, detail_json, now,
                )
        else:
            now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO user_audit_log"
                    " (tenant_id, actor, action, target, ip_address, detail, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (tenant_id, actor, action, target, ip, detail_json, now_s),
                )
                await db.commit()
        logger.info("user_audit_logged", tenant_id=tenant_id, actor=actor,
                    action=action, target=target)

    async def list_recent(self, tenant_id: str, limit: int = 50) -> list[AuditEntry]:
        if is_postgres():
            async with pg_conn() as conn:
                rows = await conn.fetch(
                    "SELECT id, tenant_id, actor, action, target, ip_address, detail, created_at"
                    " FROM lex_agents_app.user_audit_log"
                    " WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
                    tenant_id, limit,
                )
            return [_pg_row_to_entry(r) for r in rows]

        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, tenant_id, actor, action, target, ip_address, detail, created_at"
                " FROM user_audit_log"
                " WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ) as cur:
                rows_raw: list[Any] = list(await cur.fetchall())
        return [
            AuditEntry(
                id=int(r[0]), tenant_id=r[1], actor=r[2], action=r[3],
                target=r[4], ip_address=r[5],
                detail=json.loads(r[6]) if r[6] else None,
                created_at=r[7],
            )
            for r in rows_raw
        ]


def _pg_row_to_entry(r: Any) -> AuditEntry:
    detail_val = r["detail"]
    parsed: dict[str, Any] | None = None
    if detail_val:
        try:
            parsed = json.loads(detail_val)
        except (ValueError, TypeError):
            parsed = {"raw": str(detail_val)}
    return AuditEntry(
        id=int(r["id"]), tenant_id=r["tenant_id"], actor=r["actor"],
        action=r["action"], target=r["target"], ip_address=r["ip_address"],
        detail=parsed,
        created_at=_fmt_ts(r["created_at"]),
    )


def _fmt_ts(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return str(v.strftime("%Y-%m-%dT%H:%M:%S"))
    return str(v)
