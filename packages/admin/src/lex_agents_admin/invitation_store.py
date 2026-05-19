"""Invitation store — email-token invitation flow (ADR 0061).

Token is generated as 32 random bytes (hex). Only the HMAC-SHA256 hash is stored.
The raw token appears once in the API response and is never persisted or logged.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS tenant_invitations (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'analyst',
    token_hash  TEXT NOT NULL UNIQUE,
    invited_by  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    accepted_at TEXT,
    revoked_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_invitations_tenant ON tenant_invitations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invitations_email  ON tenant_invitations(email);
"""

_DDL_PG = """
CREATE TABLE IF NOT EXISTS lex_agents_app.tenant_invitations (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'analyst',
    token_hash  TEXT NOT NULL UNIQUE,
    invited_by  TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass
class InvitationRecord:
    id: str
    tenant_id: str
    email: str
    role: str
    invited_by: str
    expires_at: str
    accepted_at: str | None
    revoked_at: str | None
    created_at: str
    # raw_token is only populated when the invitation is first created
    raw_token: str = ""


class InvitationStore:
    def __init__(self, db_path: str, secret_key: str) -> None:
        self._db_path = db_path
        self._secret_key = secret_key

    async def init(self) -> None:
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(_DDL_PG)
            logger.info("invitation_store_postgres_mode")
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL_SQLITE)
            await db.commit()
        logger.info("invitation_store_initialized", db_path=self._db_path)

    def _make_token(self) -> tuple[str, str]:
        """Return (raw_token_hex, hmac_hash_hex)."""
        raw_bytes = os.urandom(32)
        raw_hex = raw_bytes.hex()
        token_hash = hmac.new(
            self._secret_key.encode(), raw_bytes, hashlib.sha256
        ).hexdigest()
        return raw_hex, token_hash

    def _hash_token(self, raw_token_hex: str) -> str:
        raw_bytes = bytes.fromhex(raw_token_hex)
        return hmac.new(
            self._secret_key.encode(), raw_bytes, hashlib.sha256
        ).hexdigest()

    async def create(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
        ttl_hours: int = 72,
    ) -> InvitationRecord:
        invitation_id = str(uuid.uuid4())
        raw_token, token_hash = self._make_token()
        now = datetime.now(UTC)
        expires = now + timedelta(hours=ttl_hours)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
        exp_s = expires.strftime("%Y-%m-%dT%H:%M:%S")

        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    """INSERT INTO lex_agents_app.tenant_invitations
                       (id, tenant_id, email, role, token_hash, invited_by, expires_at, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                    invitation_id, tenant_id, email, role, token_hash, invited_by, expires, now,
                )
        else:
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT INTO tenant_invitations
                       (id, tenant_id, email, role, token_hash, invited_by, expires_at, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (invitation_id, tenant_id, email, role, token_hash, invited_by, exp_s, now_s),
                )
                await db.commit()

        logger.info("invitation_created", invitation_id=invitation_id, tenant_id=tenant_id,
                    role=role, invited_by=invited_by)
        return InvitationRecord(
            id=invitation_id, tenant_id=tenant_id, email=email, role=role,
            invited_by=invited_by, expires_at=exp_s,
            accepted_at=None, revoked_at=None, created_at=now_s,
            raw_token=raw_token,
        )

    async def get_by_token(self, raw_token_hex: str) -> InvitationRecord | None:
        """Look up invitation by raw token. Returns None if not found or HMAC invalid."""
        try:
            token_hash = self._hash_token(raw_token_hex)
        except (ValueError, Exception):
            return None

        if is_postgres():
            async with pg_conn() as conn:
                row = await conn.fetchrow(
                    "SELECT id, tenant_id, email, role, invited_by, expires_at,"
                    " accepted_at, revoked_at, created_at"
                    " FROM lex_agents_app.tenant_invitations WHERE token_hash=$1",
                    token_hash,
                )
            if row is None:
                return None
            return InvitationRecord(
                id=row["id"], tenant_id=row["tenant_id"], email=row["email"],
                role=row["role"], invited_by=row["invited_by"],
                expires_at=_fmt_ts(row["expires_at"]),
                accepted_at=_fmt_ts(row["accepted_at"]) if row["accepted_at"] else None,
                revoked_at=_fmt_ts(row["revoked_at"]) if row["revoked_at"] else None,
                created_at=_fmt_ts(row["created_at"]),
            )

        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, tenant_id, email, role, invited_by, expires_at,"
                " accepted_at, revoked_at, created_at"
                " FROM tenant_invitations WHERE token_hash=?",
                (token_hash,),
            ) as cur:
                row_raw: Any = await cur.fetchone()
        if row_raw is None:
            return None
        return InvitationRecord(
            id=row_raw[0], tenant_id=row_raw[1], email=row_raw[2],
            role=row_raw[3], invited_by=row_raw[4],
            expires_at=row_raw[5],
            accepted_at=row_raw[6], revoked_at=row_raw[7],
            created_at=row_raw[8],
        )

    async def accept(self, invitation_id: str, username: str) -> None:
        now = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                await conn.execute(
                    "UPDATE lex_agents_app.tenant_invitations SET accepted_at=$1"
                    " WHERE id=$2",
                    now, invitation_id,
                )
        else:
            now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "UPDATE tenant_invitations SET accepted_at=? WHERE id=?",
                    (now_s, invitation_id),
                )
                await db.commit()
        logger.info("invitation_accepted", invitation_id=invitation_id, username=username)

    async def revoke(self, invitation_id: str, revoked_by: str) -> bool:
        now = datetime.now(UTC)
        if is_postgres():
            async with pg_conn() as conn:
                result = await conn.execute(
                    "UPDATE lex_agents_app.tenant_invitations SET revoked_at=$1"
                    " WHERE id=$2 AND revoked_at IS NULL AND accepted_at IS NULL",
                    now, invitation_id,
                )
            ok = str(result) != "UPDATE 0"
        else:
            now_s = now.strftime("%Y-%m-%dT%H:%M:%S")
            import aiosqlite
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "UPDATE tenant_invitations SET revoked_at=?"
                    " WHERE id=? AND revoked_at IS NULL AND accepted_at IS NULL",
                    (now_s, invitation_id),
                ) as cur:
                    changed = cur.rowcount
                await db.commit()
            ok = changed > 0
        if ok:
            logger.info("invitation_revoked", invitation_id=invitation_id, revoked_by=revoked_by)
        return ok

    async def list_pending(self, tenant_id: str) -> list[InvitationRecord]:
        now_s = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        if is_postgres():
            async with pg_conn() as conn:
                rows = await conn.fetch(
                    "SELECT id, tenant_id, email, role, invited_by, expires_at,"
                    " accepted_at, revoked_at, created_at"
                    " FROM lex_agents_app.tenant_invitations"
                    " WHERE tenant_id=$1 AND accepted_at IS NULL AND revoked_at IS NULL"
                    "   AND expires_at > $2"
                    " ORDER BY created_at DESC",
                    tenant_id, datetime.now(UTC),
                )
            return [
                InvitationRecord(
                    id=r["id"], tenant_id=r["tenant_id"], email=r["email"],
                    role=r["role"], invited_by=r["invited_by"],
                    expires_at=_fmt_ts(r["expires_at"]),
                    accepted_at=None, revoked_at=None,
                    created_at=_fmt_ts(r["created_at"]),
                )
                for r in rows
            ]
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT id, tenant_id, email, role, invited_by, expires_at,"
                " accepted_at, revoked_at, created_at"
                " FROM tenant_invitations"
                " WHERE tenant_id=? AND accepted_at IS NULL AND revoked_at IS NULL"
                "   AND expires_at > ?"
                " ORDER BY created_at DESC",
                (tenant_id, now_s),
            ) as cur:
                rows_raw: list[Any] = list(await cur.fetchall())
        return [
            InvitationRecord(
                id=r[0], tenant_id=r[1], email=r[2], role=r[3], invited_by=r[4],
                expires_at=r[5], accepted_at=r[6], revoked_at=r[7], created_at=r[8],
            )
            for r in rows_raw
        ]


def _fmt_ts(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return str(v.strftime("%Y-%m-%dT%H:%M:%S"))
    return str(v)
