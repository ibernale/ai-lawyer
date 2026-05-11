"""Resolve [REF:n] references to chunks and detect broken references."""

from __future__ import annotations

import regex
import structlog

from lex_agents_shared.types import CitationMapping

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_REF_PATTERN: regex.Pattern[str] = regex.compile(r'\[REF:(\d+)\]')


class CitationParser:
    """Resolve citation references and detect broken ones."""

    def __init__(self) -> None:
        self._index_cache: dict[int, CitationMapping] | None = None

    def _build_index(self, mapping: list[CitationMapping]) -> dict[int, CitationMapping]:
        if self._index_cache is None:
            self._index_cache = {cm.index: cm for cm in mapping}
        return self._index_cache

    def resolve(self, ref_index: int, mapping: list[CitationMapping]) -> CitationMapping | None:
        """O(1) lookup of a CitationMapping by its [REF:n] index."""
        index = self._build_index(mapping)
        result = index.get(ref_index)
        if result is None:
            logger.debug("citation_parser.unresolved_ref", ref_index=ref_index)
        return result

    def find_broken_refs(self, text: str, mapping: list[CitationMapping]) -> list[int]:
        """Return sorted list of [REF:n] indices in text that don't exist in mapping."""
        index = self._build_index(mapping)
        broken: list[int] = []
        seen: set[int] = set()

        for match in _REF_PATTERN.finditer(text):
            n = int(match.group(1))
            if n not in seen:
                seen.add(n)
                if n not in index:
                    broken.append(n)

        broken.sort()
        if broken:
            logger.warning("citation_parser.broken_refs_found", broken_refs=broken)
        return broken
