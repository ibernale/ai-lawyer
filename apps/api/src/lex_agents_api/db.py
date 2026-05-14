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
from pydantic import BaseModel

from lex_agents_shared.db import is_postgres, pg_conn

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
    cost_estimate_usd REAL
);
"""

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
            await db.commit()
        logger.info("consultation_store_initialized", db_path=self._db_path)

    async def save(self, record: ConsultationRecord) -> None:
        if is_postgres():
            await self._pg_save(record)
        else:
            await self._sqlite_save(record)

    async def get(self, trace_id: str) -> ConsultationRecord | None:
        if is_postgres():
            return await self._pg_get(trace_id)
        return await self._sqlite_get(trace_id)

    async def list_recent(self, limit: int = 20) -> list[ConsultationRecord]:
        if is_postgres():
            return await self._pg_list_recent(limit)
        return await self._sqlite_list_recent(limit)

    # ------------------------------------------------------------------
    # PostgreSQL (asyncpg)
    # ------------------------------------------------------------------

    async def _pg_save(self, record: ConsultationRecord) -> None:
        async with pg_conn() as conn:
            await conn.execute(
                """
                INSERT INTO consultations
                    (trace_id, created_at, query, response_json, verification_json,
                     prompt_versions, models, latency_ms, cost_estimate_usd)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
                ON CONFLICT (trace_id) DO UPDATE
                    SET created_at         = EXCLUDED.created_at,
                        query              = EXCLUDED.query,
                        response_json      = EXCLUDED.response_json,
                        verification_json  = EXCLUDED.verification_json,
                        prompt_versions    = EXCLUDED.prompt_versions,
                        models             = EXCLUDED.models,
                        latency_ms         = EXCLUDED.latency_ms,
                        cost_estimate_usd  = EXCLUDED.cost_estimate_usd
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
            )
        logger.debug("consultation_saved_pg", trace_id=record.trace_id)

    async def _pg_get(self, trace_id: str) -> ConsultationRecord | None:
        async with pg_conn() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM consultations WHERE trace_id = $1", trace_id
            )
        return _pg_row_to_record(row) if row else None

    async def _pg_list_recent(self, limit: int) -> list[ConsultationRecord]:
        async with pg_conn() as conn:
            rows = await conn.fetch(
                "SELECT * FROM consultations ORDER BY created_at DESC LIMIT $1", limit
            )
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
                    prompt_versions, models, latency_ms, cost_estimate_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
    )
