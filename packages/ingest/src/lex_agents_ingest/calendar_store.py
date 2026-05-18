"""Regulatory calendar — CalendarEvent model, CalendarEventStore, and CalendarSyncer.

CalendarSyncer orchestrates one or more calendar sources (currently EBA) and
persists their events into the SQLite store.  The API router reads from the
store; events are never exposed directly from the scraper.

Deadline types:
  consultation   — open consultation period / comment deadline
  application    — regulation enters into force / becomes applicable
  reporting      — supervisory reporting deadline (COREP, FINREP, etc.)
  review         — review / assessment deadline
  publication    — expected publication date for a final rule / report
  other          — everything else
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

import aiosqlite
import structlog
from pydantic import BaseModel, Field

logger: structlog.BoundLogger = structlog.get_logger(__name__)

DeadlineType = Literal[
    "consultation", "application", "reporting", "review", "publication", "other"
]

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class CalendarEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str | None = None
    event_date: date
    deadline_type: DeadlineType = "other"
    source_id: str
    url: str | None = None
    domain: str = "regulatorio_bancario_ue_es"
    jurisdiction: str = "EU"
    regulation_ref: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS calendar_events (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,
    event_date      TEXT NOT NULL,
    deadline_type   TEXT NOT NULL DEFAULT 'other',
    source_id       TEXT NOT NULL,
    url             TEXT,
    domain          TEXT NOT NULL,
    jurisdiction    TEXT NOT NULL DEFAULT 'EU',
    regulation_ref  TEXT,
    created_at      TEXT NOT NULL
);
"""

_IDX_DATE = """
CREATE INDEX IF NOT EXISTS idx_calendar_events_date
    ON calendar_events (event_date ASC);
"""

_IDX_SOURCE = """
CREATE INDEX IF NOT EXISTS idx_calendar_events_source
    ON calendar_events (source_id);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class CalendarEventStore:
    """Persists CalendarEvents in SQLite."""

    def __init__(self, db_path: str = "data/calendar.db") -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_DDL)
            await db.execute(_IDX_DATE)
            await db.execute(_IDX_SOURCE)
            await db.commit()

    async def save_event(self, event: CalendarEvent) -> None:
        """Upsert a CalendarEvent (update title/url/description if id already exists)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO calendar_events
                    (id, title, description, event_date, deadline_type, source_id,
                     url, domain, jurisdiction, regulation_ref, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    url=excluded.url
                """,
                (
                    event.id,
                    event.title,
                    event.description,
                    event.event_date.isoformat(),
                    event.deadline_type,
                    event.source_id,
                    event.url,
                    event.domain,
                    event.jurisdiction,
                    event.regulation_ref,
                    event.created_at.isoformat(),
                ),
            )
            await db.commit()

    async def list_events(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        domain: str | None = None,
        jurisdiction: str | None = None,
        deadline_type: DeadlineType | None = None,
        limit: int = 100,
    ) -> list[CalendarEvent]:
        clauses: list[str] = []
        params: list[Any] = []

        if from_date:
            clauses.append("event_date >= ?")
            params.append(from_date.isoformat())
        if to_date:
            clauses.append("event_date <= ?")
            params.append(to_date.isoformat())
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if jurisdiction:
            clauses.append("jurisdiction = ?")
            params.append(jurisdiction)
        if deadline_type:
            clauses.append("deadline_type = ?")
            params.append(deadline_type)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT id, title, description, event_date, deadline_type, source_id,
                   url, domain, jurisdiction, regulation_ref, created_at
            FROM calendar_events
            {where}
            ORDER BY event_date ASC
            LIMIT ?
        """
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()

        return [
            CalendarEvent(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                event_date=date.fromisoformat(row["event_date"]),
                deadline_type=row["deadline_type"],
                source_id=row["source_id"],
                url=row["url"],
                domain=row["domain"],
                jurisdiction=row["jurisdiction"],
                regulation_ref=row["regulation_ref"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def upcoming(self, *, days: int = 30, limit: int = 50) -> list[CalendarEvent]:
        """Return events from today until today+days."""
        today = datetime.now(UTC).date()
        from datetime import timedelta
        end = today + timedelta(days=days)
        return await self.list_events(from_date=today, to_date=end, limit=limit)

    async def count(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM calendar_events") as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Syncer
# ---------------------------------------------------------------------------


class CalendarSyncer:
    """Pulls calendar events from all sources and stores them."""

    def __init__(self, store: CalendarEventStore, source: Any = None) -> None:
        self._store = store
        self._source = source  # optional injection point; defaults to EbaCalendarSource()

    async def sync(self) -> int:
        """Run a full sync. Returns number of events upserted."""
        from lex_agents_ingest.sources.eba_calendar import (
            EbaCalendarSource,
            _parse_deadline_type,
        )

        source = self._source if self._source is not None else EbaCalendarSource()
        raw_events = await source.fetch_calendar()

        count = 0
        for raw in raw_events:
            try:
                event = CalendarEvent(
                    title=raw["title"],
                    event_date=raw["event_date"],
                    deadline_type=_parse_deadline_type(raw["title"]),  # type: ignore[arg-type]
                    source_id=raw["source_id"],
                    url=raw.get("url"),
                    domain="regulatorio_bancario_ue_es",
                    jurisdiction="EU",
                )
                await self._store.save_event(event)
                count += 1
            except Exception:
                logger.warning("calendar_syncer_event_error", raw=raw)

        logger.info("calendar_sync_complete", n_upserted=count)
        return count
