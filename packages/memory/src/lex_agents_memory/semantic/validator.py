"""YAML schema validator for docs/knowledge/ files.

Called by CI (`make validate-knowledge`) and by SemanticLoader at startup.
Emits warnings but never raises — does not block runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import structlog
import yaml

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_REQUIRED_HEADER_KEYS = {"_schema_version", "_description", "_last_updated", "_edit_policy"}

_SECTION_REQUIRED_KEYS: dict[str, dict[str, list[str]]] = {
    "jurisdictions.yaml": {
        "jurisdictions": ["code", "name", "supervisor_prudential", "currency", "regime"],
    },
    "internal-glossary.yaml": {
        "glossary": ["term", "description"],
    },
    "regulatory-frameworks.yaml": {
        "frameworks": ["id", "full_name", "jurisdiction", "branches"],
    },
    "output-templates.yaml": {
        "templates": ["output_type", "structure", "mandatory_caveat"],
    },
}


def _validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"{path.name}: YAML parse error — {exc}"]

    # Header keys
    missing_header = _REQUIRED_HEADER_KEYS - set(data.keys())
    if missing_header:
        errors.append(f"{path.name}: missing header keys {sorted(missing_header)}")

    # Section-specific required fields
    rules = _SECTION_REQUIRED_KEYS.get(path.name, {})
    for section, required_fields in rules.items():
        entries = data.get(section)
        if entries is None:
            errors.append(f"{path.name}: missing section '{section}'")
            continue
        if not isinstance(entries, list):
            errors.append(f"{path.name}: section '{section}' must be a list")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"{path.name}[{section}][{i}]: must be a mapping")
                continue
            for field in required_fields:
                if field not in entry:
                    errors.append(f"{path.name}[{section}][{i}]: missing field '{field}'")

    return errors


def validate_all(knowledge_dir: Path) -> list[str]:
    """Validate all YAML files in knowledge_dir. Returns list of error strings."""
    if not knowledge_dir.exists():
        return [f"Knowledge directory not found: {knowledge_dir}"]

    all_errors: list[str] = []
    yaml_files = sorted(knowledge_dir.glob("*.yaml"))
    if not yaml_files:
        logger.warning("semantic_validator_no_files", dir=str(knowledge_dir))
        return []

    for yaml_file in yaml_files:
        errs = _validate_file(yaml_file)
        if errs:
            logger.warning(
                "semantic_validator_errors",
                file=yaml_file.name,
                n_errors=len(errs),
            )
        all_errors.extend(errs)

    if not all_errors:
        logger.info("semantic_validator_ok", n_files=len(yaml_files))
    return all_errors


def main() -> None:
    """CLI entry point for `make validate-knowledge`."""
    knowledge_dir = Path("docs/knowledge")
    errors = validate_all(knowledge_dir)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {len(list(knowledge_dir.glob('*.yaml')))} YAML files validated.")
    sys.exit(0)


if __name__ == "__main__":
    main()
