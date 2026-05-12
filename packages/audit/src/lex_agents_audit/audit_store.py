"""SQLite-backed audit sample store."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import aiosqlite
import structlog
from pydantic import BaseModel

logger: structlog.BoundLogger = structlog.get_logger(__name__)

AuditStatus = Literal["pending", "reviewing", "reviewed"]
AuditVerdict = Literal["correcto", "dudoso", "incorrecto"]

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

_INSERT = """
INSERT INTO audit_samples
    (trace_id, query, response_json, branch, depth, sampled_at, status)
VALUES (?, ?, ?, ?, ?, ?, 'pending')
"""

_UPDATE_REVIEW = """
UPDATE audit_samples
SET status = 'reviewed', reviewer = ?, review_notes = ?, review_verdict = ?
WHERE id = ?
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
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        logger.info("audit_store_initialized", db_path=self._db_path)

    async def save(self, record: AuditSampleRecord) -> int:
        """Insert a new audit sample and return its auto-generated integer ID."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                _INSERT,
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

    async def submit_review(
        self,
        sample_id: int,
        reviewer: str,
        notes: str,
        verdict: AuditVerdict,
    ) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                _UPDATE_REVIEW, (reviewer, notes, verdict, sample_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get(self, sample_id: int) -> AuditSampleRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM audit_samples WHERE id = ?", (sample_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return _row_to_record(row) if row else None

    async def list_by_status(
        self, status: AuditStatus | None = None, limit: int = 50
    ) -> list[AuditSampleRecord]:
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
        return [_row_to_record(r) for r in rows]

    async def list_negative(self, since_days: int = 30) -> list[AuditSampleRecord]:
        """Return reviewed samples with verdict='incorrecto' in the last N days."""
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM audit_samples WHERE review_verdict = 'incorrecto' AND sampled_at >= ? ORDER BY sampled_at DESC",
                (cutoff,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_record(r) for r in rows]

    async def count_pending(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM audit_samples WHERE status = 'pending'"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0


def _row_to_record(row: aiosqlite.Row) -> AuditSampleRecord:
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
