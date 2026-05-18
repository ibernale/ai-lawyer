"""SemanticLoader — loads and caches docs/knowledge/ YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

from lex_agents_memory.semantic.validator import validate_all
from lex_agents_memory.types import SemanticEntry

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_SECTION_KEYS = {
    "jurisdictions.yaml": "jurisdictions",
    "internal-glossary.yaml": "glossary",
    "regulatory-frameworks.yaml": "frameworks",
    "output-templates.yaml": "templates",
}

# Top-level keys expected inside a specialist YAML file
_SPECIALIST_KEYS = (
    "key_regulations",
    "common_caveats",
    "jurisprudence",
    "regulatory_contacts",
)


class SemanticLoader:
    """Loads semantic memory from docs/knowledge/ YAMLs.

    Validates on construction (warning only — never raises).
    Results cached in-process after first load.
    """

    def __init__(self, knowledge_dir: Path) -> None:
        self._dir = knowledge_dir
        self._cache: dict[str, list[SemanticEntry]] | None = None

        if knowledge_dir.exists():
            errors = validate_all(knowledge_dir)
            if errors:
                logger.warning(
                    "semantic_loader_validation_warnings",
                    n_errors=len(errors),
                    errors=errors[:5],
                )
        else:
            logger.warning("semantic_loader_dir_not_found", dir=str(knowledge_dir))

    def load_all(self) -> dict[str, list[SemanticEntry]]:
        """Load all YAML files, keyed by section name. Cached after first call."""
        if self._cache is not None:
            return self._cache

        result: dict[str, list[SemanticEntry]] = {}
        if not self._dir.exists():
            self._cache = result
            return result

        for filename, section_key in _SECTION_KEYS.items():
            path = self._dir / filename
            if not path.exists():
                logger.warning("semantic_loader_file_missing", file=filename)
                continue
            try:
                data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
                entries_raw = data.get(section_key, [])
                if not isinstance(entries_raw, list):
                    logger.warning("semantic_loader_section_not_list", file=filename, section=section_key)
                    continue
                entries = [
                    SemanticEntry(
                        source_file=filename,
                        section=section_key,
                        content=entry,
                    )
                    for entry in entries_raw
                    if isinstance(entry, dict)
                ]
                result[section_key] = entries
                logger.info(
                    "semantic_loader_loaded",
                    file=filename,
                    section=section_key,
                    n_entries=len(entries),
                )
            except Exception:
                logger.exception("semantic_loader_error", file=filename)

        self._cache = result
        return result

    def load_specialist(self, branch: str) -> dict[str, list[SemanticEntry]]:
        """Load the specialist YAML for *branch* from ``knowledge_dir/specialists/``.

        Returns a dict keyed by section name (``key_regulations``,
        ``common_caveats``, ``jurisprudence``, ``regulatory_contacts``).
        Returns ``{}`` if the file does not exist (not all branches have one yet).
        """
        specialists_dir = self._dir / "specialists"
        path = specialists_dir / f"{branch}.yaml"
        if not path.exists():
            logger.debug("semantic_loader_specialist_not_found", branch=branch, path=str(path))
            return {}

        try:
            data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        except Exception:
            logger.exception("semantic_loader_specialist_error", branch=branch)
            return {}

        result: dict[str, list[SemanticEntry]] = {}
        for key in _SPECIALIST_KEYS:
            entries_raw = data.get(key, [])
            if not isinstance(entries_raw, list):
                continue
            result[key] = [
                SemanticEntry(
                    source_file=f"specialists/{branch}.yaml",
                    section=key,
                    content=entry,
                )
                for entry in entries_raw
                if isinstance(entry, dict)
            ]

        logger.info(
            "semantic_loader_specialist_loaded",
            branch=branch,
            sections={k: len(v) for k, v in result.items()},
        )
        return result

    def load_for_query(
        self,
        jurisdictions: list[str],
        output_type: str | None = None,
    ) -> dict[str, list[SemanticEntry]]:
        """Return entries relevant to the given jurisdictions and output_type."""
        all_data = self.load_all()
        result: dict[str, list[SemanticEntry]] = {}

        # Jurisdictions: filter to requested codes + always include EU
        wanted = {j.upper() for j in jurisdictions} | {"EU"}
        jur_entries = all_data.get("jurisdictions", [])
        result["jurisdictions"] = [
            e for e in jur_entries
            if e.content.get("code", "").upper() in wanted
        ]

        # Glossary: always include all (small)
        result["glossary"] = all_data.get("glossary", [])

        # Frameworks: filter to relevant jurisdictions
        fw_entries = all_data.get("frameworks", [])
        result["frameworks"] = [
            e for e in fw_entries
            if e.content.get("jurisdiction", "").upper() in wanted
            or e.content.get("jurisdiction", "").upper() == "GLOBAL"
        ]

        # Templates: filter to requested output_type if given
        tpl_entries = all_data.get("templates", [])
        if output_type:
            result["templates"] = [
                e for e in tpl_entries
                if e.content.get("output_type") == output_type
            ]
        else:
            result["templates"] = tpl_entries

        return result
