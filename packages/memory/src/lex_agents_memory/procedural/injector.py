"""ProceduralInjector — matches patterns to query and builds context block."""

from __future__ import annotations

import structlog

from lex_agents_memory.types import ProceduralPattern

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class ProceduralInjector:
    """Selects and formats procedural patterns relevant to a query."""

    def match(
        self,
        query: str,
        output_type: str | None,
        patterns: list[ProceduralPattern],
    ) -> list[ProceduralPattern]:
        """Return patterns whose applies_when conditions match query/output_type.

        A pattern matches if:
        - At least one keyword in applies_when.keywords appears in the query (case-insensitive), OR
        - output_type is in applies_when.output_types.
        Patterns with empty applies_when always match.
        """
        query_lower = query.lower()
        matched: list[ProceduralPattern] = []

        for pattern in patterns:
            aw = pattern.applies_when
            if not aw:
                # No condition → always applies
                matched.append(pattern)
                continue

            keywords: list[str] = aw.get("keywords", [])
            output_types: list[str] = aw.get("output_types", [])

            keyword_match = any(kw.lower() in query_lower for kw in keywords)
            type_match = output_type is not None and output_type in output_types

            if keyword_match or type_match:
                matched.append(pattern)

        logger.info(
            "procedural_injector_matched",
            total=len(patterns),
            matched=len(matched),
        )
        return matched

    def build_context(self, matched: list[ProceduralPattern]) -> str:
        """Format matched patterns into a Markdown block. Returns '' if empty."""
        if not matched:
            return ""

        lines = ["## Patrones Procedimentales Aplicables\n"]
        for p in matched:
            lines.append(f"### {p.pattern_key} (v{p.version})\n{p.instructions}\n")

        return "\n".join(lines)
