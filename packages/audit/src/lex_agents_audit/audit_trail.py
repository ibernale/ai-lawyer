"""Append-only audit trail with SHA-256 checksum chain (ADR 0035).

The audit_trail table is protected by SQLite triggers that reject any UPDATE
or DELETE. Each row includes a chained SHA-256 checksum for tamper detection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Closed enumeration of auditable action types.
ACTION_TYPES: frozenset[str] = frozenset({
    "system.kill_switch.engage",
    "system.kill_switch.release",
    "system.flag.change",
    "agent.prompt.promote",
    "agent.prompt.reject",
    "agent.prompt.preview",
    "source.pause",
    "source.resume",
    "source.force_resync",
    "memory.procedural.edit",
    "memory.semantic.edit",
    "audit_sample.review",
    "prompt_evolution_pr.approve",
    "prompt_evolution_pr.reject",
    "prompt_evolution_pr.request_changes",
    "user.role.change",
    "export.audit_trail",
})

_DDL = """
CREATE TABLE IF NOT EXISTS audit_trail (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    actor_user_id    TEXT    NOT NULL,
    actor_role       TEXT    NOT NULL,
    action_type      TEXT    NOT NULL,
    target_type      TEXT    NOT NULL,
    target_id        TEXT,
    before_state     TEXT,
    after_state      TEXT,
    reason           TEXT    NOT NULL,
    correlation_id   TEXT,
    checksum_prev    TEXT,
    checksum_self    TEXT
);

CREATE TRIGGER IF NOT EXISTS audit_trail_no_update
BEFORE UPDATE ON audit_trail
BEGIN
    SELECT RAISE(ABORT, 'audit_trail is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_trail_no_delete
BEFORE DELETE ON audit_trail
BEGIN
    SELECT RAISE(ABORT, 'audit_trail is append-only');
END;

CREATE TABLE IF NOT EXISTS prompt_evolution_proposals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number        INTEGER UNIQUE,
    pr_url           TEXT    NOT NULL,
    specialist       TEXT    NOT NULL,
    diff             TEXT    NOT NULL,
    motivating_cases TEXT,
    simulation_results TEXT,
    status           TEXT    NOT NULL DEFAULT 'pending',
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    decided_at       TEXT,
    decided_by       TEXT,
    decision_reason  TEXT
);

CREATE TABLE IF NOT EXISTS source_status (
    source_id        TEXT PRIMARY KEY,
    display_name     TEXT,
    status           TEXT    NOT NULL DEFAULT 'active',
    paused_at        TEXT,
    paused_by        TEXT,
    paused_reason    TEXT,
    last_synced_at   TEXT
);
"""

_SOURCES_SEED = [
    ("boe",     "BOE — Boletín Oficial del Estado"),
    ("eur_lex", "EUR-Lex — European Union Law"),
    ("cendoj",  "CENDOJ — Jurisprudencia"),
    ("bde",     "BdE — Banco de España"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    id: int
    timestamp: str
    actor_user_id: str
    actor_role: str
    action_type: str
    target_type: str
    target_id: str | None
    before_state: str | None
    after_state: str | None
    reason: str
    correlation_id: str | None
    checksum_prev: str | None
    checksum_self: str | None


@dataclass
class ChainVerificationResult:
    valid: bool
    total: int
    broken_at: int | None  # row id where chain breaks, None if intact


@dataclass
class PromptEvolutionProposal:
    id: int
    pr_number: int | None
    pr_url: str
    specialist: str
    diff: str
    motivating_cases: str | None
    simulation_results: str | None
    status: str
    created_at: str
    decided_at: str | None
    decided_by: str | None
    decision_reason: str | None


@dataclass
class SourceStatusRow:
    source_id: str
    display_name: str | None
    status: str
    paused_at: str | None
    paused_by: str | None
    paused_reason: str | None
    last_synced_at: str | None


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_manager: AuditTrailManager | None = None


def get_audit_trail_manager() -> AuditTrailManager | None:
    return _manager


def set_audit_trail_manager(m: AuditTrailManager) -> None:
    global _manager
    _manager = m


# ---------------------------------------------------------------------------
# Core manager
# ---------------------------------------------------------------------------

def _compute_checksum(
    timestamp: str,
    actor: str,
    action_type: str,
    before: str | None,
    after: str | None,
    reason: str,
    checksum_prev: str | None,
) -> str:
    """Chain checksum excludes row_id so it can be computed before INSERT."""
    payload = f"{timestamp}|{actor}|{action_type}|{before}|{after}|{reason}|{checksum_prev}"
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditTrailManager:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL)
            # Seed sources if empty
            async with db.execute("SELECT COUNT(*) FROM source_status") as cur:
                count = (await cur.fetchone())[0]  # type: ignore[index]
            if count == 0:
                await db.executemany(
                    "INSERT OR IGNORE INTO source_status (source_id, display_name) VALUES (?,?)",
                    _SOURCES_SEED,
                )
            await db.commit()
        logger.info("audit_trail_initialized", db_path=self._db_path)

    async def log(
        self,
        action_type: str,
        target_type: str,
        actor: str,
        actor_role: str,
        reason: str,
        *,
        target_id: str | None = None,
        before: Any = None,
        after: Any = None,
        correlation_id: str | None = None,
    ) -> int:
        if action_type not in ACTION_TYPES:
            raise ValueError(f"Unknown action_type '{action_type}'. Extend ACTION_TYPES via ADR.")
        if not reason.strip():
            raise ValueError("reason must not be empty")

        before_str = json.dumps(before, default=str) if before is not None else None
        after_str = json.dumps(after, default=str) if after is not None else None
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        async with aiosqlite.connect(self._db_path) as db:
            # Get last checksum_self for chaining (computed before insert)
            async with db.execute(
                "SELECT checksum_self FROM audit_trail ORDER BY id DESC LIMIT 1"
            ) as cur:
                last = await cur.fetchone()
            checksum_prev = last[0] if last else None

            # Compute checksum before inserting (excludes row_id to avoid chicken-and-egg)
            checksum_self = _compute_checksum(
                ts, actor, action_type, before_str, after_str, reason, checksum_prev
            )

            async with db.execute(
                """INSERT INTO audit_trail
                   (timestamp, actor_user_id, actor_role, action_type, target_type,
                    target_id, before_state, after_state, reason, correlation_id,
                    checksum_prev, checksum_self)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, actor, actor_role, action_type, target_type,
                 target_id, before_str, after_str, reason, correlation_id,
                 checksum_prev, checksum_self),
            ) as cur:
                final_id: int = cur.lastrowid  # type: ignore[assignment]

            await db.commit()

        logger.info(
            "audit_trail_entry",
            id=final_id,
            action_type=action_type,
            actor=actor,
            target_type=target_type,
        )
        return final_id

    async def get_history(
        self,
        *,
        actor: str | None = None,
        action_type: str | None = None,
        target_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        conditions: list[str] = []
        params: list[Any] = []
        if actor:
            conditions.append("actor_user_id = ?")
            params.append(actor)
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)
        if target_type:
            conditions.append("target_type = ?")
            params.append(target_type)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                f"""SELECT id, timestamp, actor_user_id, actor_role, action_type,
                           target_type, target_id, before_state, after_state, reason,
                           correlation_id, checksum_prev, checksum_self
                    FROM audit_trail {where}
                    ORDER BY id DESC LIMIT ?""",
                params,
            ) as cur:
                rows = await cur.fetchall()

        return [AuditEntry(*r) for r in rows]

    async def get_entry(self, entry_id: int) -> AuditEntry | None:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """SELECT id, timestamp, actor_user_id, actor_role, action_type,
                          target_type, target_id, before_state, after_state, reason,
                          correlation_id, checksum_prev, checksum_self
                   FROM audit_trail WHERE id = ?""",
                (entry_id,),
            ) as cur:
                row = await cur.fetchone()
        return AuditEntry(*row) if row else None

    async def verify_chain(self) -> ChainVerificationResult:
        """Walk every row in insertion order and recompute checksums."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """SELECT id, timestamp, actor_user_id, action_type,
                          before_state, after_state, reason, checksum_prev, checksum_self
                   FROM audit_trail ORDER BY id ASC"""
            ) as cur:
                rows: list[Any] = list(await cur.fetchall())

        total = len(rows)
        for row in rows:
            rid, ts, actor, atype, before, after, reason, cp, cs = row
            expected = _compute_checksum(ts, actor, atype, before, after, reason, cp)
            if expected != cs:
                return ChainVerificationResult(valid=False, total=total, broken_at=rid)

        return ChainVerificationResult(valid=True, total=total, broken_at=None)

    # ------------------------------------------------------------------
    # Prompt evolution proposals
    # ------------------------------------------------------------------

    async def save_proposal(
        self,
        pr_url: str,
        specialist: str,
        diff: str,
        *,
        pr_number: int | None = None,
        motivating_cases: str | None = None,
        simulation_results: str | None = None,
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """INSERT INTO prompt_evolution_proposals
                   (pr_number, pr_url, specialist, diff, motivating_cases, simulation_results)
                   VALUES (?,?,?,?,?,?)""",
                (pr_number, pr_url, specialist, diff, motivating_cases, simulation_results),
            ) as cur:
                row_id: int = cur.lastrowid  # type: ignore[assignment]
            await db.commit()
        return row_id

    async def list_proposals(self, status: str | None = None) -> list[PromptEvolutionProposal]:
        cond = "WHERE status = ?" if status else ""
        params: list[Any] = [status] if status else []
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                f"""SELECT id, pr_number, pr_url, specialist, diff, motivating_cases,
                           simulation_results, status, created_at, decided_at,
                           decided_by, decision_reason
                    FROM prompt_evolution_proposals {cond}
                    ORDER BY created_at DESC""",
                params,
            ) as cur:
                rows = await cur.fetchall()
        return [PromptEvolutionProposal(*r) for r in rows]

    async def update_proposal_status(
        self,
        pr_number: int,
        status: str,
        decided_by: str,
        decision_reason: str,
    ) -> bool:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """UPDATE prompt_evolution_proposals
                   SET status=?, decided_at=?, decided_by=?, decision_reason=?
                   WHERE pr_number=?""",
                (status, ts, decided_by, decision_reason, pr_number),
            ) as cur:
                changed = cur.rowcount
            await db.commit()
        return changed > 0

    # ------------------------------------------------------------------
    # Source status
    # ------------------------------------------------------------------

    async def list_sources(self) -> list[SourceStatusRow]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT source_id, display_name, status, paused_at, paused_by, paused_reason, last_synced_at FROM source_status ORDER BY source_id"
            ) as cur:
                rows = await cur.fetchall()
        return [SourceStatusRow(*r) for r in rows]

    async def set_source_status(
        self,
        source_id: str,
        new_status: str,
        *,
        paused_by: str | None = None,
        paused_reason: str | None = None,
    ) -> bool:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        paused_at = ts if new_status == "paused" else None
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                """UPDATE source_status
                   SET status=?, paused_at=?, paused_by=?, paused_reason=?
                   WHERE source_id=?""",
                (new_status, paused_at, paused_by, paused_reason, source_id),
            ) as cur:
                changed = cur.rowcount
            await db.commit()
        return changed > 0
