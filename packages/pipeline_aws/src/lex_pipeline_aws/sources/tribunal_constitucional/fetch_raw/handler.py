"""fetch_raw handler for Tribunal Constitucional — Lambda step in ingest_tc state machine.

AMBER source — schedule disabled by default.
Status: ADR 0011 AMBER — blocked until Legal del Grupo confirms that TC terms
of use permit automated bulk access. See docs/legal/cendoj-status.md.

This handler raises NotImplementedError to prevent accidental activation.
To enable: update TribunalConstitucionalSource from AMBER to GREEN in
packages/ingest/src/lex_agents_ingest/sources/__init__.py and implement
the fetch logic below.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AMBER source — raises NotImplementedError until Legal clearance obtained."""
    # AMBER source — schedule disabled by default
    # Do not activate without Legal del Grupo sign-off (see docs/legal/cendoj-status.md)
    raise NotImplementedError(
        "TribunalConstitucional: ADR 0011 AMBER — pendiente verificación de términos de uso. "
        "Ver docs/legal/cendoj-status.md"
    )
