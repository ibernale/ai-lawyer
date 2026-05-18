"""Consultation and feedback stores — dual-mode: Aurora (asyncpg) or SQLite (aiosqlite).

Mode selection:
  - DATABASE_URL set → asyncpg (Aurora Serverless v2 / lex_agents_app schema)
  - DATABASE_URL not set → aiosqlite (local dev, data/consultations.db)

Both modes expose identical public APIs; callers never need to check the mode.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn
from pydantic import BaseModel

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQLite DDL (local dev only)
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS consultations (
    trace_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    query TEXT NOT NULL,
    response_json TEXT NOT NULL,
    verification_json TEXT,
    prompt_versions TEXT,
    models TEXT,
    latency_ms INTEGER,
    cost_estimate_usd REAL,
    depth_used TEXT,
    branch TEXT
);
"""

_MIGRATE_ADD_DEPTH = "ALTER TABLE consultations ADD COLUMN depth_used TEXT"
_MIGRATE_ADD_BRANCH = "ALTER TABLE consultations ADD COLUMN branch TEXT"

_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------

class ConsultationRecord(BaseModel):
    trace_id: str
    created_at: datetime
    query: str
    response_json: str
    verification_json: str | None = None
    prompt_versions: dict[str, int] | None = None
    models: list[str] | None = None
    latency_ms: int | None = None
    cost_estimate_usd: float | None = None
    depth_used: str | None = None
    branch: str | None = None


class FeedbackRecord(BaseModel):
    id: int | None = None
    trace_id: str
    verdict: str  # aceptable | dudoso | incorrecto
    notes: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# ConsultationStore
# ---------------------------------------------------------------------------

class ConsultationStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        if is_postgres():
            # Schema managed by Alembic migrations — nothing to create.
            logger.info("consultation_store_postgres_mode")
            return
        import aiosqlite
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            # Migrate existing databases that lack the new columns.
            for stmt in (_MIGRATE_ADD_DEPTH, _MIGRATE_ADD_BRANCH):
                try:
                    await db.execute(stmt)
                except Exception as exc:
                    logger.debug("migration_column_already_exists", stmt=stmt, exc=str(exc))
            await db.commit()
        logger.info("consultation_store_initialized", db_path=self._db_path)

    async def save(self, record: ConsultationRecord, *, tenant_id: str = "default") -> None:
        if is_postgres():
            await self._pg_save(record, tenant_id=tenant_id)
        else:
            await self._sqlite_save(record)

    async def get(self, trace_id: str, *, tenant_id: str = "default") -> ConsultationRecord | None:
        if is_postgres():
            return await self._pg_get(trace_id, tenant_id=tenant_id)
        return await self._sqlite_get(trace_id)

    async def list_recent(self, limit: int = 20, *, tenant_id: str = "default") -> list[ConsultationRecord]:
        if is_postgres():
            return await self._pg_list_recent(limit, tenant_id=tenant_id)
        return await self._sqlite_list_recent(limit)

    async def search(
        self,
        q: str | None = None,
        depth: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
        offset: int = 0,
        *,
        tenant_id: str = "default",
    ) -> list[ConsultationRecord]:
        if is_postgres():
            return await self._pg_search(q, depth, branch, status, since, until, limit, offset, tenant_id=tenant_id)
        return await self._sqlite_search(q, depth, branch, status, since, until, limit, offset)

    # ------------------------------------------------------------------
    # PostgreSQL (asyncpg)
    # ------------------------------------------------------------------

    async def _pg_save(self, record: ConsultationRecord, *, tenant_id: str = "default") -> None:
        async with pg_conn(tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO consultations
                    (trace_id, created_at, query, response_json, verification_json,
                     prompt_versions, models, latency_ms, cost_estimate_usd,
                     depth_used, branch)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11)
                ON CONFLICT (trace_id) DO UPDATE
                    SET created_at         = EXCLUDED.created_at,
                        query              = EXCLUDED.query,
                        response_json      = EXCLUDED.response_json,
                        verification_json  = EXCLUDED.verification_json,
                        prompt_versions    = EXCLUDED.prompt_versions,
                        models             = EXCLUDED.models,
                        latency_ms         = EXCLUDED.latency_ms,
                        cost_estimate_usd  = EXCLUDED.cost_estimate_usd,
                        depth_used         = EXCLUDED.depth_used,
                        branch             = EXCLUDED.branch
                """,
                record.trace_id,
                record.created_at,
                record.query,
                record.response_json,
                record.verification_json,
                json.dumps(record.prompt_versions) if record.prompt_versions else None,
                json.dumps(record.models) if record.models else None,
                record.latency_ms,
                record.cost_estimate_usd,
                record.depth_used,
                record.branch,
            )
        logger.debug("consultation_saved_pg", trace_id=record.trace_id, tenant_id=tenant_id)

    async def _pg_get(self, trace_id: str, *, tenant_id: str = "default") -> ConsultationRecord | None:
        async with pg_conn(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consultations WHERE trace_id = $1", trace_id
            )
        return _pg_row_to_record(row) if row else None

    async def _pg_list_recent(self, limit: int, *, tenant_id: str = "default") -> list[ConsultationRecord]:
        async with pg_conn(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT * FROM consultations ORDER BY created_at DESC LIMIT $1", limit
            )
        return [_pg_row_to_record(r) for r in rows]

    async def _pg_search(
        self,
        q: str | None,
        depth: str | None,
        branch: str | None,
        status: str | None,
        since: str | None,
        until: str | None,
        limit: int,
        offset: int,
        *,
        tenant_id: str = "default",
    ) -> list[ConsultationRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        idx = 1

        # Full-text search via tsvector/tsquery (migration 0003).
        # Two modes:
        #   multi-word or explicit operators → plainto_tsquery (phrase-aware)
        #   single word                      → to_tsquery with :* suffix for
        #                                      prefix matching
        tsquery_expr: str | None = None
        if q:
            stripped = q.strip()
            words = stripped.split()
            has_operators = any(op in stripped for op in ("&", "|", ":*"))
            if len(words) >= 2 or has_operators:
                tsquery_expr = f"plainto_tsquery('spanish', ${idx})"
                params.append(stripped)
            else:
                tsquery_expr = f"to_tsquery('spanish', ${idx} || ':*')"
                params.append(stripped)
            clauses.append(f"search_vector @@ {tsquery_expr}")
            idx += 1

        if depth:
            clauses.append(f"depth_used = ${idx}")
            params.append(depth)
            idx += 1
        if branch:
            clauses.append(f"branch = ${idx}")
            params.append(branch)
            idx += 1
        if status:
            clauses.append(f"verification_json::jsonb->>'status' = ${idx}")
            params.append(status)
            idx += 1
        if since:
            clauses.append(f"created_at >= ${idx}")
            params.append(since)
            idx += 1
        if until:
            clauses.append(f"created_at <= ${idx}")
            params.append(until)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        # When searching, rank by relevance first then recency; otherwise by
        # recency alone.
        if tsquery_expr is not None:
            order_by = f"ORDER BY ts_rank(search_vector, {tsquery_expr}) DESC, created_at DESC"
        else:
            order_by = "ORDER BY created_at DESC"

        params += [limit, offset]
        sql = (
            f"SELECT * FROM consultations {where} {order_by}"  # noqa: S608
            f" LIMIT ${idx} OFFSET ${idx + 1}"
        )
        async with pg_conn(tenant_id) as conn:
            rows = await conn.fetch(sql, *params)
        return [_pg_row_to_record(r) for r in rows]

    # ------------------------------------------------------------------
    # SQLite (aiosqlite) — local dev
    # ------------------------------------------------------------------

    async def _sqlite_save(self, record: ConsultationRecord) -> None:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO consultations
                   (trace_id, created_at, query, response_json, verification_json,
                    prompt_versions, models, latency_ms, cost_estimate_usd,
                    depth_used, branch)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.trace_id,
                    record.created_at.isoformat(),
                    record.query,
                    record.response_json,
                    record.verification_json,
                    json.dumps(record.prompt_versions) if record.prompt_versions else None,
                    json.dumps(record.models) if record.models else None,
                    record.latency_ms,
                    record.cost_estimate_usd,
                    record.depth_used,
                    record.branch,
                ),
            )
            await db.commit()
        logger.debug("consultation_saved", trace_id=record.trace_id)

    async def _sqlite_get(self, trace_id: str) -> ConsultationRecord | None:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM consultations WHERE trace_id = ?", (trace_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return _sqlite_row_to_record(row) if row else None

    async def _sqlite_list_recent(self, limit: int) -> list[ConsultationRecord]:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM consultations ORDER BY created_at DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [_sqlite_row_to_record(r) for r in rows]

    async def _sqlite_search(
        self,
        q: str | None,
        depth: str | None,
        branch: str | None,
        status: str | None,
        since: str | None,
        until: str | None,
        limit: int,
        offset: int,
    ) -> list[ConsultationRecord]:
        import aiosqlite
        clauses: list[str] = []
        params: list[Any] = []

        if q:
            clauses.append("query LIKE ?")
            params.append(f"%{q}%")
        if depth:
            clauses.append("depth_used = ?")
            params.append(depth)
        if branch:
            clauses.append("branch = ?")
            params.append(branch)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM consultations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"  # noqa: S608
        params += [limit, offset]

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

        results = [_sqlite_row_to_record(r) for r in rows]
        # status filter applied in Python — verification_json is stored as a JSON string
        if status:
            results = [r for r in results if _extract_verification_status(r.verification_json) == status]
        return results


# ---------------------------------------------------------------------------
# FeedbackStore
# ---------------------------------------------------------------------------

class FeedbackStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        if is_postgres():
            logger.info("feedback_store_postgres_mode")
            return
        import aiosqlite
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_FEEDBACK_TABLE)
            await db.commit()

    async def save(self, trace_id: str, verdict: str, notes: str | None) -> None:
        if is_postgres():
            await self._pg_save(trace_id, verdict, notes)
        else:
            await self._sqlite_save(trace_id, verdict, notes)

    async def list_recent(self, limit: int = 50) -> list[FeedbackRecord]:
        if is_postgres():
            return await self._pg_list_recent(limit)
        return await self._sqlite_list_recent(limit)

    async def list_negative(self, since_days: int = 30) -> list[FeedbackRecord]:
        if is_postgres():
            return await self._pg_list_negative(since_days)
        return await self._sqlite_list_negative(since_days)

    # ------------------------------------------------------------------
    # PostgreSQL (asyncpg)
    # ------------------------------------------------------------------

    async def _pg_save(self, trace_id: str, verdict: str, notes: str | None) -> None:
        async with pg_conn() as conn:
            await conn.execute(
                """INSERT INTO user_feedback (trace_id, verdict, notes, created_at)
                   VALUES ($1, $2, $3, $4)""",
                trace_id, verdict, notes, datetime.now(UTC),
            )
        logger.debug("feedback_saved_pg", trace_id=trace_id, verdict=verdict)

    async def _pg_list_recent(self, limit: int) -> list[FeedbackRecord]:
        async with pg_conn() as conn:
            rows = await conn.fetch(
                "SELECT * FROM user_feedback ORDER BY created_at DESC LIMIT $1", limit
            )
        return [_pg_row_to_feedback(r) for r in rows]

    async def _pg_list_negative(self, since_days: int) -> list[FeedbackRecord]:
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        async with pg_conn() as conn:
            rows = await conn.fetch(
                """SELECT * FROM user_feedback
                   WHERE verdict = 'incorrecto' AND created_at >= $1
                   ORDER BY created_at DESC""",
                cutoff,
            )
        return [_pg_row_to_feedback(r) for r in rows]

    # ------------------------------------------------------------------
    # SQLite (aiosqlite) — local dev
    # ------------------------------------------------------------------

    async def _sqlite_save(self, trace_id: str, verdict: str, notes: str | None) -> None:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO user_feedback (trace_id, verdict, notes, created_at) VALUES (?, ?, ?, ?)",
                (trace_id, verdict, notes, datetime.now(UTC).isoformat()),
            )
            await db.commit()
        logger.debug("feedback_saved", trace_id=trace_id, verdict=verdict)

    async def _sqlite_list_recent(self, limit: int) -> list[FeedbackRecord]:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_feedback ORDER BY created_at DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            FeedbackRecord(
                id=row["id"], trace_id=row["trace_id"], verdict=row["verdict"],
                notes=row["notes"], created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def _sqlite_list_negative(self, since_days: int) -> list[FeedbackRecord]:
        from datetime import timedelta

        import aiosqlite
        cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_feedback WHERE verdict = 'incorrecto' AND created_at >= ? ORDER BY created_at DESC",
                (cutoff,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            FeedbackRecord(
                id=row["id"], trace_id=row["trace_id"], verdict=row["verdict"],
                notes=row["notes"], created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------

def _extract_verification_status(verification_json: str | None) -> str:
    if not verification_json:
        return "pending"
    try:
        data: dict[str, object] = json.loads(verification_json)
        return str(data.get("status", "unknown"))
    except Exception:
        return "unknown"


def _pg_row_to_record(row: Any) -> ConsultationRecord:
    pv = row["prompt_versions"]
    mds = row["models"]
    return ConsultationRecord(
        trace_id=row["trace_id"],
        created_at=row["created_at"],
        query=row["query"],
        response_json=row["response_json"] or "",
        verification_json=row["verification_json"],
        prompt_versions=dict(pv) if pv is not None else None,
        models=list(mds) if mds is not None else None,
        latency_ms=row["latency_ms"],
        cost_estimate_usd=float(row["cost_estimate_usd"]) if row["cost_estimate_usd"] is not None else None,
        depth_used=row["depth_used"],
        branch=row["branch"],
    )


def _pg_row_to_feedback(row: Any) -> FeedbackRecord:
    return FeedbackRecord(
        id=row["id"],
        trace_id=row["trace_id"],
        verdict=row["verdict"],
        notes=row["notes"],
        created_at=row["created_at"],
    )


def _sqlite_row_to_record(row: Any) -> ConsultationRecord:
    return ConsultationRecord(
        trace_id=row["trace_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        query=row["query"],
        response_json=row["response_json"],
        verification_json=row["verification_json"],
        prompt_versions=json.loads(row["prompt_versions"]) if row["prompt_versions"] else None,
        models=json.loads(row["models"]) if row["models"] else None,
        latency_ms=row["latency_ms"],
        cost_estimate_usd=row["cost_estimate_usd"],
        depth_used=row["depth_used"],
        branch=row["branch"],
    )
