"""PlaybookLoader — loads and caches negotiation playbooks from YAML files."""

from __future__ import annotations

import re
from pathlib import Path

import structlog
import yaml

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_PLAYBOOKS_DIR = Path(__file__).parent / "playbooks"

# In-memory cache: (contract_type, party_role) -> list of clause dicts
_CACHE: dict[tuple[str, str], list[dict]] = {}  # type: ignore[type-arg]


def _normalize(value: str) -> str:
    """Convert a display name to snake_case directory name.

    Examples:
        "LoanAgreement"     -> "loan_agreement"
        "NDA"               -> "nda"
        "ServiceAgreement"  -> "service_agreement"
        "DataProcessingAgreement" -> "data_processing_agreement"
    """
    # Insert underscore before uppercase runs that follow lowercase letters
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    # Insert underscore between consecutive uppercase letters followed by lowercase
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


def get_playbook(contract_type: str, party_role: str) -> list[dict]:  # type: ignore[type-arg]
    """Return the list of clause playbook entries for the given contract type and party role.

    Normalises ``contract_type`` to a snake_case directory name and looks up
    ``<playbooks_dir>/<contract_type>/<party_role>.yaml``.

    Returns an empty list if the playbook file is not found (graceful degradation).
    """
    normalized_type = _normalize(contract_type)
    normalized_role = party_role.lower().strip()
    cache_key = (normalized_type, normalized_role)

    if cache_key in _CACHE:
        return _CACHE[cache_key]

    playbook_path = _PLAYBOOKS_DIR / normalized_type / f"{normalized_role}.yaml"

    if not playbook_path.exists():
        logger.info(
            "playbook_not_found",
            contract_type=normalized_type,
            party_role=normalized_role,
            path=str(playbook_path),
        )
        _CACHE[cache_key] = []
        return []

    try:
        with playbook_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        logger.warning(
            "playbook_load_error",
            contract_type=normalized_type,
            party_role=normalized_role,
            path=str(playbook_path),
            error=str(exc),
        )
        _CACHE[cache_key] = []
        return []

    clauses: list[dict] = data.get("clauses", []) if isinstance(data, dict) else []  # type: ignore[type-arg]
    logger.info(
        "playbook_loaded",
        contract_type=normalized_type,
        party_role=normalized_role,
        num_clauses=len(clauses),
    )
    _CACHE[cache_key] = clauses
    return clauses


def get_playbook_summary(contract_type: str, party_role: str) -> str:
    """Return a compact textual summary of the playbook for use in LLM prompts.

    Includes only clause titles and preferred-position summaries, keeping
    the prompt size manageable.
    """
    clauses = get_playbook(contract_type, party_role)
    if not clauses:
        return f"No playbook found for {contract_type} / {party_role}."

    lines: list[str] = [
        f"PLAYBOOK: {contract_type.upper()} — {party_role.upper()} perspective\n"
    ]
    for clause in clauses:
        title = clause.get("clause_title", "Unknown Clause")
        preferred = clause.get("preferred_position", {})
        summary = preferred.get("summary", "")
        prevalence = preferred.get("market_prevalence", "")
        never_accept = clause.get("never_accept", [])
        escalation = clause.get("escalation_to", "")

        lines.append(f"## {title}")
        if summary:
            # Truncate to 300 chars to keep prompt compact
            truncated = summary.strip()[:300]
            lines.append(f"  Preferred: {truncated}")
        if prevalence:
            lines.append(f"  Market prevalence: {prevalence:.0%}")
        if never_accept:
            never_labels = "; ".join(
                na.get("condition", "")[:120] for na in never_accept[:2]
            )
            lines.append(f"  NEVER ACCEPT: {never_labels}")
        if escalation:
            lines.append(f"  Escalate to: {escalation}")
        lines.append("")

    return "\n".join(lines)


def clear_cache() -> None:
    """Clear the in-memory playbook cache (useful for tests)."""
    _CACHE.clear()
