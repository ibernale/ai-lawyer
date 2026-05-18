"""Regulation change monitor — detects new/amended documents across sources.

Architecture:
  - ChangeEvent: one event per newly detected document.
  - ChangeEventStore: aiosqlite persistence (checkpoint + events tables).
  - ChangeMonitor: orchestrates sources, diffs against checkpoint, emits events.

Severity heuristic (no LLM — keep this fast and offline-capable):
  high   — keywords: "urgente", "emergencia", "deroga", "ley", "reglamento",
            "regulation", "directive", "mandatory"
  medium — keywords: "circular", "instrucción", "guideline", "guidance",
            "recommendation", "norma"
  low    — everything else
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

import aiosqlite
import structlog
from pydantic import BaseModel, Field

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

ChangeType = Literal["new", "amendment", "repeal"]
Severity = Literal["high", "medium", "low"]


class ChangeEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    document_id: str
    title: str
    url: str | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    change_type: ChangeType = "new"
    domain: str = "regulatorio_bancario_ue_es"
    severity: Severity = "medium"
    summary: str | None = None
    read: bool = False


# ---------------------------------------------------------------------------
# Severity heuristic
# ---------------------------------------------------------------------------

_HIGH_RE = re.compile(
    r"\b(urgent[eo]?|emergencia|deroga|law|ley|reglamento|regulation|directive|mandatory|obligatorio)\b",
    re.IGNORECASE,
)
_MEDIUM_RE = re.compile(
    r"\b(circular|instrucción|guideline|guidance|recommendation|recomendaci[oó]n|norma|notice)\b",
    re.IGNORECASE,
)


def classify_severity(title: str) -> Severity:
    """Heuristic severity based on title keywords (no LLM, offline-safe)."""
    if _HIGH_RE.search(title):
        return "high"
    if _MEDIUM_RE.search(title):
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DDL_CHECKPOINT = """
CREATE TABLE IF NOT EXISTS monitor_checkpoint (
    source_id   TEXT    NOT NULL,
    document_id TEXT    NOT NULL,
    seen_at     TEXT    NOT NULL,
    PRIMARY KEY (source_id, document_id)
);
"""

_DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS monitor_events (
    id          TEXT    PRIMARY KEY,
    source_id   TEXT    NOT NULL,
    document_id TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    url         TEXT,
    detected_at TEXT    NOT NULL,
    change_type TEXT    NOT NULL DEFAULT 'new',
    domain      TEXT    NOT NULL,
    severity    TEXT    NOT NULL DEFAULT 'medium',
    summary     TEXT,
    read        INTEGER NOT NULL DEFAULT 0
);
"""

_IDX_EVENTS_DETECTED = """
CREATE INDEX IF NOT EXISTS idx_monitor_events_detected_at
    ON monitor_events (detected_at DESC);
"""


class ChangeEventStore:
    """Persists ChangeEvents and source checkpoints in SQLite."""

    def __init__(self, db_path: str = "data/monitor.db") -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_DDL_CHECKPOINT)
            await db.execute(_DDL_EVENTS)
            await db.execute(_IDX_EVENTS_DETECTED)
            await db.commit()

    async def is_known(self, source_id: str, document_id: str) -> bool:
        """Return True if (source_id, document_id) is already in the checkpoint."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT 1 FROM monitor_checkpoint WHERE source_id=? AND document_id=?",
                (source_id, document_id),
            ) as cur:
                return await cur.fetchone() is not None

    async def mark_seen(self, source_id: str, document_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO monitor_checkpoint (source_id, document_id, seen_at) VALUES (?,?,?)",
                (source_id, document_id, datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def save_event(self, event: ChangeEvent) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO monitor_events
                    (id, source_id, document_id, title, url, detected_at,
                     change_type, domain, severity, summary, read)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.id,
                    event.source_id,
                    event.document_id,
                    event.title,
                    event.url,
                    event.detected_at.isoformat(),
                    event.change_type,
                    event.domain,
                    event.severity,
                    event.summary,
                    int(event.read),
                ),
            )
            await db.commit()

    async def list_events(
        self,
        *,
        limit: int = 50,
        unread_only: bool = False,
        severity: Severity | None = None,
        domain: str | None = None,
    ) -> list[ChangeEvent]:
        clauses: list[str] = []
        params: list[str | int] = []

        if unread_only:
            clauses.append("read = 0")
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT id, source_id, document_id, title, url, detected_at,
                   change_type, domain, severity, summary, read
            FROM monitor_events
            {where}
            ORDER BY detected_at DESC
            LIMIT ?
        """
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()

        return [
            ChangeEvent(
                id=row["id"],
                source_id=row["source_id"],
                document_id=row["document_id"],
                title=row["title"],
                url=row["url"],
                detected_at=datetime.fromisoformat(row["detected_at"]),
                change_type=row["change_type"],
                domain=row["domain"],
                severity=row["severity"],
                summary=row["summary"],
                read=bool(row["read"]),
            )
            for row in rows
        ]

    async def mark_read(self, event_id: str) -> bool:
        """Mark an event as read. Returns True if the event was found."""
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "UPDATE monitor_events SET read=1 WHERE id=?", (event_id,)
            )
            await db.commit()
            return cur.rowcount > 0

    async def unread_count(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM monitor_events WHERE read=0"
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Source protocol (minimal — avoids circular imports)
# ---------------------------------------------------------------------------

@runtime_checkable
class _SourceProto(Protocol):
    """Structural type — any object with source_id and list_documents()."""
    source_id: str

    async def list_documents(self) -> list[str]: ...  # pragma: no cover


# ---------------------------------------------------------------------------
# ChangeMonitor
# ---------------------------------------------------------------------------

# Domain mapping from source_id
_SOURCE_DOMAIN: dict[str, str] = {
    "boe": "regulatorio_bancario_ue_es",
    "eurlex": "regulatorio_bancario_ue_es",
    "cnmc": "regulatorio_bancario_ue_es",
    "sepblac": "aml_compliance",
    "bcbs_bis": "regulatorio_bancario_ue_es",
    "federal_register": "aml_compliance",
    "bcb_brasil": "regulatorio_bancario_ue_es",
    "bcra": "regulatorio_bancario_ue_es",
}


class ChangeMonitor:
    """Scans sources, diffs against the checkpoint, and emits ChangeEvents."""

    def __init__(
        self,
        sources: Sequence[_SourceProto],
        store: ChangeEventStore,
    ) -> None:
        self._sources = sources
        self._store = store

    async def scan(self) -> list[ChangeEvent]:
        """Run a full scan across all sources and return new ChangeEvents."""
        new_events: list[ChangeEvent] = []

        for source in self._sources:
            try:
                doc_ids = await source.list_documents()
            except Exception:
                logger.exception("change_monitor_list_error", source_id=source.source_id)
                continue

            for doc_id in doc_ids:
                try:
                    if await self._store.is_known(source.source_id, doc_id):
                        continue

                    await self._store.mark_seen(source.source_id, doc_id)

                    event = ChangeEvent(
                        source_id=source.source_id,
                        document_id=doc_id,
                        title=doc_id,  # title = doc_id until fetch enriches it
                        domain=_SOURCE_DOMAIN.get(source.source_id, "regulatorio_bancario_ue_es"),
                        severity=classify_severity(doc_id),
                        change_type="new",
                    )
                    await self._store.save_event(event)
                    new_events.append(event)

                    logger.info(
                        "change_monitor_new_event",
                        source_id=source.source_id,
                        doc_id=doc_id,
                        severity=event.severity,
                    )

                except Exception:
                    logger.exception(
                        "change_monitor_doc_error",
                        source_id=source.source_id,
                        doc_id=doc_id,
                    )

        logger.info("change_monitor_scan_complete", n_new=len(new_events))
        return new_events
