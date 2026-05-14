"""parse_canonical handler for Tribunal Constitucional — Lambda step in ingest_tc state machine.

AMBER source — schedule disabled by default.
See fetch_raw/handler.py for status details.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AMBER source — raises NotImplementedError until Legal clearance obtained."""
    # AMBER source — schedule disabled by default
    raise NotImplementedError(
        "TribunalConstitucional: ADR 0011 AMBER — pendiente verificación de términos de uso. "
        "Ver docs/legal/cendoj-status.md"
    )
