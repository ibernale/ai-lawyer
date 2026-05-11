"""SemanticInjector — formats semantic knowledge into a Planner context block."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from lex_agents_memory.semantic.loader import SemanticLoader

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Approximate token budget for semantic context (chars / 4 ≈ tokens)
_BUDGET_CHARS = 8000  # ~2000 tokens


def _format_jurisdiction(e: dict[str, Any]) -> str:
    code = e.get("code", "?")
    name = e.get("name", "")
    sup_pru = e.get("supervisor_prudential", "")
    sup_con = e.get("supervisor_conduct", "")
    regime = e.get("regime", "")
    parts = [f"**{code}** ({name})"]
    if sup_pru:
        parts.append(f"supervisor prudencial: {sup_pru}")
    if sup_con:
        parts.append(f"supervisor conducta: {sup_con}")
    if regime:
        parts.append(f"régimen: {regime}")
    return " | ".join(parts)


def _format_glossary(e: dict[str, Any]) -> str:
    term = e.get("term", "?")
    abbr = e.get("abbreviation", "")
    desc = e.get("description", "")
    abbr_str = f" ({abbr})" if abbr else ""
    return f"- **{term}{abbr_str}**: {desc}"


def _format_framework(e: dict[str, Any]) -> str:
    fid = e.get("id", "?")
    name = e.get("full_name", "")
    jur = e.get("jurisdiction", "")
    celex = e.get("celex", "")
    branches = ", ".join(e.get("branches", []))
    parts = [f"**{fid}**: {name} [{jur}]"]
    if celex:
        parts.append(f"CELEX:{celex}")
    if branches:
        parts.append(f"ramas: {branches}")
    return " | ".join(parts)


def _format_template(e: dict[str, Any]) -> str:
    otype = e.get("output_type", "?")
    structure = e.get("structure", [])
    caveat = e.get("mandatory_caveat", "")
    lines = [f"**Plantilla {otype}**:", "Estructura:"]
    lines.extend(f"  {s}" for s in structure)
    if caveat:
        lines.append(f"Cautela obligatoria: _{caveat[:200]}_")
    return "\n".join(lines)


class SemanticInjector:
    """Formats semantic memory entries into a Markdown context block for the Planner."""

    def __init__(self, loader: SemanticLoader) -> None:
        self._loader = loader

    @classmethod
    def from_dir(cls, knowledge_dir: Path) -> SemanticInjector:
        return cls(SemanticLoader(knowledge_dir))

    def build_context(
        self,
        jurisdictions: list[str],
        output_type: str | None = None,
    ) -> str:
        """Build a formatted Markdown context block. Returns '' if no data."""
        data = self._loader.load_for_query(jurisdictions, output_type)
        if not any(data.values()):
            return ""

        sections: list[str] = ["## Memoria Semántica Institucional\n"]
        total_chars = len(sections[0])

        # Jurisdictions
        jur_entries = data.get("jurisdictions", [])
        if jur_entries:
            block = "### Jurisdicciones activas\n" + "\n".join(
                _format_jurisdiction(e.content) for e in jur_entries
            )
            if total_chars + len(block) < _BUDGET_CHARS:
                sections.append(block)
                total_chars += len(block)

        # Output template (most important for Planner)
        tpl_entries = data.get("templates", [])
        if tpl_entries:
            block = "### Plantilla de output\n" + "\n\n".join(
                _format_template(e.content) for e in tpl_entries[:1]  # max 1 template
            )
            if total_chars + len(block) < _BUDGET_CHARS:
                sections.append(block)
                total_chars += len(block)

        # Regulatory frameworks (truncate if budget exceeded)
        fw_entries = data.get("frameworks", [])
        if fw_entries:
            fw_lines = []
            for e in fw_entries:
                line = _format_framework(e.content)
                if total_chars + len(line) + 50 >= _BUDGET_CHARS:
                    fw_lines.append("_(marcos adicionales omitidos por presupuesto de tokens)_")
                    break
                fw_lines.append(line)
                total_chars += len(line)
            if fw_lines:
                sections.append("### Marcos normativos relevantes\n" + "\n".join(fw_lines))

        # Glossary (compact, only if budget remains)
        gls_entries = data.get("glossary", [])
        if gls_entries and total_chars < _BUDGET_CHARS * 0.8:
            block = "### Nomenclatura interna\n" + "\n".join(
                _format_glossary(e.content) for e in gls_entries[:10]
            )
            if total_chars + len(block) < _BUDGET_CHARS:
                sections.append(block)

        context = "\n\n".join(sections)
        logger.info(
            "semantic_injector_built",
            jurisdictions=jurisdictions,
            output_type=output_type,
            chars=len(context),
        )
        return context
