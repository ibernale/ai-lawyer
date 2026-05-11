"""ProceduralLoader — loads patterns from SQLite or a seed SQL file (tests)."""

from __future__ import annotations

import re
import sqlite3
import tempfile
from pathlib import Path

import structlog

from lex_agents_memory.types import ProceduralPattern
from lex_agents_memory.procedural import store

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class ProceduralLoader:
    """Loads procedural patterns from the SQLite store.

    Accepts optional db_path and seed_sql_path for initialization.
    If db_path is None, uses an in-memory DB populated from seed (useful in tests).
    """

    def __init__(
        self,
        db_path: Path | None = None,
        seed_sql_path: Path | None = None,
    ) -> None:
        self._db_path = db_path
        self._seed_sql_path = seed_sql_path
        self._cache: list[ProceduralPattern] | None = None

    def load(self) -> list[ProceduralPattern]:
        """Load active patterns, with lazy init and caching."""
        if self._cache is not None:
            return self._cache

        if self._db_path is None:
            # In-memory from seed — for tests and environments without a DB
            patterns = self._load_from_seed_in_memory()
        else:
            if not self._db_path.exists() and self._seed_sql_path:
                store.init_db(self._db_path, self._seed_sql_path)
            patterns = store.get_active_patterns(self._db_path)

        self._cache = patterns
        return patterns

    def _load_from_seed_in_memory(self) -> list[ProceduralPattern]:
        if not self._seed_sql_path or not self._seed_sql_path.exists():
            logger.warning("procedural_loader_no_seed")
            return []
        try:
            with sqlite3.connect(":memory:") as conn:
                conn.execute(store._SCHEMA_SQL)
                conn.executescript(self._seed_sql_path.read_text())
                conn.commit()
                rows = conn.execute(store._SELECT_ACTIVE).fetchall()
            patterns = [store._row_to_pattern(r) for r in rows]
            logger.info("procedural_loader_in_memory", n_patterns=len(patterns))
            return patterns
        except Exception:
            logger.exception("procedural_loader_seed_error")
            return []
