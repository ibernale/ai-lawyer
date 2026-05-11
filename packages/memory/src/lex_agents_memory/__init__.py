"""lex-agents-memory — stratified memory subsystem (ADR 0013).

Provides MemoryInjector that combines semantic (YAML) and procedural (SQLite)
memory into a formatted context block for the LegalPlanner.

Usage:
    from lex_agents_memory import MemoryInjector
    injector = MemoryInjector(
        knowledge_dir=Path("docs/knowledge"),
        db_path=Path("data/procedural.db"),
        seed_sql_path=Path("packages/memory/seed/procedural_patterns_seed.sql"),
    )
    context = injector.build_context(
        query="¿Qué ratio de capital exige el CRR?",
        jurisdictions=["ES", "EU"],
        output_type="dictamen",
    )
"""

from __future__ import annotations

from pathlib import Path

import structlog

from lex_agents_memory.types import ProceduralPattern, SemanticEntry
from lex_agents_memory.semantic.injector import SemanticInjector
from lex_agents_memory.semantic.loader import SemanticLoader
from lex_agents_memory.procedural.injector import ProceduralInjector
from lex_agents_memory.procedural.loader import ProceduralLoader

logger: structlog.BoundLogger = structlog.get_logger(__name__)

__all__ = ["MemoryInjector", "SemanticEntry", "ProceduralPattern"]


class MemoryInjector:
    """Combines semantic and procedural memory into a single context block.

    Gracefully degrades: if knowledge_dir or db_path are missing, the
    corresponding memory type returns '' and the Planner operates normally.
    """

    def __init__(
        self,
        knowledge_dir: Path | None = None,
        db_path: Path | None = None,
        seed_sql_path: Path | None = None,
    ) -> None:
        self._semantic = SemanticInjector(
            SemanticLoader(knowledge_dir or Path("docs/knowledge"))
        )
        self._proc_loader = ProceduralLoader(
            db_path=db_path,
            seed_sql_path=seed_sql_path,
        )
        self._proc_injector = ProceduralInjector()

    def build_context(
        self,
        query: str,
        jurisdictions: list[str] | None = None,
        output_type: str | None = None,
    ) -> str:
        """Build combined memory context. Returns '' if both memories are empty."""
        jurisdictions = jurisdictions or []

        semantic_ctx = self._semantic.build_context(
            jurisdictions=jurisdictions,
            output_type=output_type,
        )

        patterns = self._proc_loader.load()
        matched = self._proc_injector.match(query, output_type, patterns)
        procedural_ctx = self._proc_injector.build_context(matched)

        parts = [p for p in [semantic_ctx, procedural_ctx] if p]
        if not parts:
            return ""

        combined = "\n\n---\n\n".join(parts)
        logger.info(
            "memory_injector_built",
            semantic_chars=len(semantic_ctx),
            procedural_patterns=len(matched),
            total_chars=len(combined),
        )
        return combined
