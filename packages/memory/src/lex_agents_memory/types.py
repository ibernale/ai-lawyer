"""Shared types for the lex-agents memory subsystem (ADR 0013)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


@dataclass
class SemanticEntry:
    """A single entry loaded from a docs/knowledge/ YAML file."""

    source_file: str
    """Filename relative to docs/knowledge/, e.g. 'jurisdictions.yaml'."""
    section: str
    """Top-level YAML key, e.g. 'jurisdictions', 'glossary', 'frameworks', 'templates'."""
    content: dict[str, Any]
    """The raw dict for this entry."""


@dataclass
class ProceduralPattern:
    """A row from the procedural_patterns SQLite table (ADR 0013)."""

    id: int
    pattern_key: str
    """Namespaced key, e.g. 'output_template:dictamen', 'routing:crr_caveat'."""
    version: int
    content: str
    """JSON string containing instructions and applies_when conditions."""
    source: str
    """Provenance: 'human:seed' or 'human:pr#N'."""
    active: bool

    @property
    def applies_when(self) -> dict[str, Any]:
        """Parse applies_when from content JSON. Returns {} on error."""
        import json
        try:
            data = json.loads(self.content)
            return cast(dict[str, Any], data.get("applies_when", {}))
        except Exception:
            return {}

    @property
    def instructions(self) -> str:
        """Parse instructions from content JSON. Returns raw content on error."""
        import json
        try:
            data = json.loads(self.content)
            return str(data.get("instructions", self.content))
        except Exception:
            return self.content
