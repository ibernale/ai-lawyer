"""ProceduralStore — SQLite-backed procedural memory (ADR 0013).

INVARIANT: This module exposes NO INSERT, UPDATE, or DELETE operations.
The agent has read-only access at runtime.
Write access is exclusively via `make procedural-edit` (seed SQL file + PR).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import structlog

from lex_agents_memory.types import ProceduralPattern

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ── INVARIANT: Do NOT add INSERT/UPDATE/DELETE methods to this class. ─────────
# Procedural memory is human-curated. Agent writes would create an unaudited
# self-modification loop in a legal advice context (ADR 0013).
# ──────────────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS procedural_patterns (
    id          INTEGER PRIMARY KEY,
    pattern_key TEXT NOT NULL UNIQUE,
    version     INTEGER NOT NULL DEFAULT 1,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);
"""

_SELECT_ACTIVE = """
SELECT id, pattern_key, version, content, source, active
FROM procedural_patterns
WHERE active = 1
ORDER BY id;
"""


def _row_to_pattern(row: tuple[Any, ...]) -> ProceduralPattern:
    id_, key, version, content, source, active = row
    return ProceduralPattern(
        id=id_,
        pattern_key=key,
        version=version,
        content=content,
        source=source,
        active=bool(active),
    )


def init_db(db_path: Path, seed_sql_path: Path | None = None) -> None:
    """Create the schema and optionally seed from a SQL file.

    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    Seeds only if the table is empty and seed_sql_path is provided.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_SCHEMA_SQL)
        conn.commit()

        if seed_sql_path and seed_sql_path.exists():
            count = conn.execute("SELECT COUNT(*) FROM procedural_patterns").fetchone()[0]
            if count == 0:
                seed_sql = seed_sql_path.read_text()
                conn.executescript(seed_sql)
                conn.commit()
                seeded = conn.execute("SELECT COUNT(*) FROM procedural_patterns").fetchone()[0]
                logger.info("procedural_store_seeded", n_patterns=seeded, db=str(db_path))
            else:
                logger.debug("procedural_store_already_seeded", n_rows=count)

    logger.info("procedural_store_initialized", db=str(db_path))


def get_active_patterns(db_path: Path) -> list[ProceduralPattern]:
    """Return all active patterns. Returns [] if DB does not exist."""
    if not db_path.exists():
        logger.warning("procedural_store_db_not_found", db=str(db_path))
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(_SELECT_ACTIVE).fetchall()
        patterns = [_row_to_pattern(r) for r in rows]
        logger.info("procedural_store_loaded", n_patterns=len(patterns))
        return patterns
    except Exception:
        logger.exception("procedural_store_error", db=str(db_path))
        return []
