"""Audit sample store — dual-mode: Aurora (asyncpg) or SQLite (aiosqlite).

Aurora schema (lex_agents_app.audit_samples) is simpler than the SQLite schema:
it stores trace_id + metadata for external review. The full query/response_json
fields are not in Aurora's audit_samples table but are retrievable via the
consultations table by trace_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from lex_agents_shared.db import is_postgres, pg_conn
from pydantic import BaseModel

logger: structlog.BoundLogger = structlog.get_logger(__name__)

AuditStatus = Literal["pending", "reviewing", "reviewed"]
AuditVerdict = Literal["correcto", "dudoso", "incorrecto"]

# SQLite DDL (local dev only)
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    query TEXT NOT NULL,
    response_json TEXT NOT NULL,
    branch TEXT NOT NULL,
    depth TEXT NOT NULL,
    sampled_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    review_notes TEXT,
    review_verdict TEXT
);
"""


class AuditSampleRecord(BaseModel):
    id: int | None = None
    trace_id: str
    query: str
    response_json: str
    branch: str
    depth: str
    sampled_at: datetime
    status: AuditStatus = "pending"
    reviewer: str | None = None
    review_notes: str | None = None
    review_verdict: AuditVerdict | None = None


class AuditStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        if is_postgres():
            logger.info("audit_store_postgres_mode")
            return
        import aiosqlite
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        logger.info("audit_store_initialized", db_path=self._db_path)

    async def save(self, record: AuditSampleRecord) -> int:
        """Insert a new audit sample and return its auto-generated integer ID."""
        if is_postgres():
            return await self._pg_save(record)
        return await self._sqlite_save(record)

    async def submit_review(
        self,
        sample_id: int,
        reviewer: str,
        notes: str,
        verdict: AuditVerdict,
    ) -> bool:
        if is_postgres():
            return await self._pg_submit_review(sample_id, reviewer, notes, verdict)
        return await self._sqlite_submit_review(sample_id, reviewer, notes, verdict)

    async def get(self, sample_id: int) -> AuditSampleRecord | None:
        if is_postgres():
            return await self._pg_get(sample_id)
        return await self._sqlite_get(sample_id)

    async def list_by_status(
        self, status: AuditStatus | None = None, limit: int = 50
    ) -> list[AuditSampleRecord]:
        if is_postgres():
            return await self._pg_list_by_status(status, limit)
        return await self._sqlite_list_by_status(status, limit)

    async def list_negative(self, since_days: int = 30) -> list[AuditSampleRecord]:
        if is_postgres():
            return await self._pg_list_negative(since_days)
        return await self._sqlite_list_negative(since_days)

    async def find_by_trace_id(self, trace_id: str) -> AuditSampleRecord | None:
        """Return the first audit sample matching *trace_id*, or None."""
        if is_postgres():
            return await self._pg_find_by_trace_id(trace_id)
        return await self._sqlite_find_by_trace_id(trace_id)

    async def count_pending(self) -> int:
        if is_postgres():
            async with pg_conn() as conn:
                return int(await conn.fetchval(
                    "SELECT COUNT(*) FROM audit_samples WHERE reviewer IS NULL"
                ))
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM audit_samples WHERE status = 'pending'"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # PostgreSQL (asyncpg)
    # ------------------------------------------------------------------

    async def _pg_save(self, record: AuditSampleRecord) -> int:
        async with pg_conn() as conn:
            row_id: int = await conn.fetchval(
                """INSERT INTO audit_samples (trace_id, sampled_at)
                   VALUES ($1, $2)
                   RETURNING id""",
                record.trace_id,
                record.sampled_at,
            )
        logger.info("audit_sample_saved_pg", trace_id=record.trace_id, id=row_id)
        return row_id

    async def _pg_submit_review(
        self, sample_id: int, reviewer: str, notes: str, verdict: AuditVerdict
    ) -> bool:
        async with pg_conn() as conn:
            result = await conn.execute(
                """UPDATE audit_samples
                   SET reviewer=$1, notes=$2, verdict=$3, reviewed_at=$4
                   WHERE id=$5""",
                reviewer, notes, verdict, datetime.now(UTC), sample_id,
            )
        return str(result) != "UPDATE 0"

    async def _pg_get(self, sample_id: int) -> AuditSampleRecord | None:
        async with pg_conn() as conn:
            row = await conn.fetchrow(
                "SELECT id, trace_id, sampled_at, reviewer, reviewed_at, verdict, notes FROM audit_samples WHERE id = $1",
                sample_id,
            )
        if row is None:
            return None
        return _pg_row_to_record(row)

    async def _pg_list_by_status(self, status: AuditStatus | None, limit: int) -> list[AuditSampleRecord]:
        async with pg_conn() as conn:
            if status:
                # Map status to Aurora schema: pending = no reviewer
                if status == "pending":
                    rows = await conn.fetch(
                        "SELECT id, trace_id, sampled_at, reviewer, reviewed_at, verdict, notes FROM audit_samples WHERE reviewer IS NULL ORDER BY sampled_at DESC LIMIT $1",
                        limit,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT id, trace_id, sampled_at, reviewer, reviewed_at, verdict, notes FROM audit_samples WHERE reviewer IS NOT NULL ORDER BY sampled_at DESC LIMIT $1",
                        limit,
                    )
            else:
                rows = await conn.fetch(
                    "SELECT id, trace_id, sampled_at, reviewer, reviewed_at, verdict, notes FROM audit_samples ORDER BY sampled_at DESC LIMIT $1",
                    limit,
                )
        return [_pg_row_to_record(r) for r in rows]

    async def _pg_list_negative(self, since_days: int) -> list[AuditSampleRecord]:
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        async with pg_conn() as conn:
            rows = await conn.fetch(
                "SELECT id, trace_id, sampled_at, reviewer, reviewed_at, verdict, notes FROM audit_samples WHERE verdict = 'incorrecto' AND sampled_at >= $1 ORDER BY sampled_at DESC",
                cutoff,
            )
        return [_pg_row_to_record(r) for r in rows]

    async def _pg_find_by_trace_id(self, trace_id: str) -> AuditSampleRecord | None:
        async with pg_conn() as conn:
            row = await conn.fetchrow(
                "SELECT id, trace_id, sampled_at, reviewer, reviewed_at, verdict, notes FROM audit_samples WHERE trace_id = $1 LIMIT 1",
                trace_id,
            )
        return _pg_row_to_record(row) if row else None

    # ------------------------------------------------------------------
    # SQLite (aiosqlite)
    # ------------------------------------------------------------------

    async def _sqlite_save(self, record: AuditSampleRecord) -> int:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """INSERT INTO audit_samples
                   (trace_id, query, response_json, branch, depth, sampled_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    record.trace_id,
                    record.query,
                    record.response_json,
                    record.branch,
                    record.depth,
                    record.sampled_at.isoformat(),
                ),
            )
            await db.commit()
            row_id: int = cursor.lastrowid  # type: ignore[assignment]
        logger.info("audit_sample_saved", trace_id=record.trace_id, id=row_id)
        return row_id

    async def _sqlite_submit_review(
        self, sample_id: int, reviewer: str, notes: str, verdict: AuditVerdict
    ) -> bool:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "UPDATE audit_samples SET status='reviewed', reviewer=?, review_notes=?, review_verdict=? WHERE id=?",
                (reviewer, notes, verdict, sample_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def _sqlite_get(self, sample_id: int) -> AuditSampleRecord | None:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM audit_samples WHERE id = ?", (sample_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return _sqlite_row_to_record(row) if row else None

    async def _sqlite_list_by_status(self, status: AuditStatus | None, limit: int) -> list[AuditSampleRecord]:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                async with db.execute(
                    "SELECT * FROM audit_samples WHERE status = ? ORDER BY sampled_at DESC LIMIT ?",
                    (status, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with db.execute(
                    "SELECT * FROM audit_samples ORDER BY sampled_at DESC LIMIT ?",
                    (limit,),
                ) as cursor:
                    rows = await cursor.fetchall()
        return [_sqlite_row_to_record(r) for r in rows]

    async def _sqlite_list_negative(self, since_days: int) -> list[AuditSampleRecord]:
        from datetime import timedelta

        import aiosqlite
        cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM audit_samples WHERE review_verdict = 'incorrecto' AND sampled_at >= ? ORDER BY sampled_at DESC",
                (cutoff,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_sqlite_row_to_record(r) for r in rows]

    async def _sqlite_find_by_trace_id(self, trace_id: str) -> AuditSampleRecord | None:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM audit_samples WHERE trace_id = ? LIMIT 1", (trace_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return _sqlite_row_to_record(row) if row else None


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------

def _pg_row_to_record(row: Any) -> AuditSampleRecord:
    sampled = row["sampled_at"]
    return AuditSampleRecord(
        id=row["id"],
        trace_id=row["trace_id"],
        query="",  # not stored in Aurora audit_samples; retrieve via consultations
        response_json="",
        branch="",
        depth="",
        sampled_at=sampled if hasattr(sampled, "tzinfo") else datetime.fromisoformat(str(sampled)),
        status="reviewed" if row["reviewer"] else "pending",
        reviewer=row["reviewer"],
        review_notes=row["notes"],
        review_verdict=row["verdict"],
    )


def _sqlite_row_to_record(row: Any) -> AuditSampleRecord:
    return AuditSampleRecord(
        id=row["id"],
        trace_id=row["trace_id"],
        query=row["query"],
        response_json=row["response_json"],
        branch=row["branch"],
        depth=row["depth"],
        sampled_at=datetime.fromisoformat(row["sampled_at"]),
        status=row["status"],
        reviewer=row["reviewer"],
        review_notes=row["review_notes"],
        review_verdict=row["review_verdict"],
    )
