"""SQLite-backed consultation history store (async via aiosqlite)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import structlog
from pydantic import BaseModel

logger: structlog.BoundLogger = structlog.get_logger(__name__)

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

_INSERT = """
INSERT OR REPLACE INTO consultations
    (trace_id, created_at, query, response_json, verification_json,
     prompt_versions, models, latency_ms, cost_estimate_usd)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


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


class ConsultationStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        logger.info("consultation_store_initialized", db_path=self._db_path)

    async def save(self, record: ConsultationRecord) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                _INSERT,
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

    async def get(self, trace_id: str) -> ConsultationRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM consultations WHERE trace_id = ?", (trace_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    async def list_recent(self, limit: int = 20) -> list[ConsultationRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM consultations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_record(r) for r in rows]


def _row_to_record(row: aiosqlite.Row) -> ConsultationRecord:
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


# ---------------------------------------------------------------------------
# User feedback store
# ---------------------------------------------------------------------------

_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS user_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""

_INSERT_FEEDBACK = """
INSERT INTO user_feedback (trace_id, verdict, notes, created_at)
VALUES (?, ?, ?, ?)
"""


class FeedbackRecord(BaseModel):
    id: int | None = None
    trace_id: str
    verdict: str  # aceptable | dudoso | incorrecto
    notes: str | None = None
    created_at: datetime


class FeedbackStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_FEEDBACK_TABLE)
            await db.commit()

    async def save(self, trace_id: str, verdict: str, notes: str | None) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                _INSERT_FEEDBACK,
                (trace_id, verdict, notes, datetime.now(UTC).isoformat()),
            )
            await db.commit()
        logger.debug("feedback_saved", trace_id=trace_id, verdict=verdict)

    async def list_recent(self, limit: int = 50) -> list[FeedbackRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_feedback ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            FeedbackRecord(
                id=row["id"],
                trace_id=row["trace_id"],
                verdict=row["verdict"],
                notes=row["notes"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def list_negative(self, since_days: int = 30) -> list[FeedbackRecord]:
        """Return feedback with verdict='incorrecto' in the last N days."""
        from datetime import timedelta

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
                id=row["id"],
                trace_id=row["trace_id"],
                verdict=row["verdict"],
                notes=row["notes"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
