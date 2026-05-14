"""parse_canonical handler for CENDOJ — Lambda step in ingest_cendoj state machine.

AMBER source — schedule disabled by default.
See fetch_raw/handler.py for status details.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AMBER source — raises NotImplementedError until CGPJ authorisation obtained."""
    # AMBER source — schedule disabled by default
    raise NotImplementedError(
        "CENDOJ: ADR 0011 AMBER — pendiente autorización CGPJ. "
        "Ver docs/legal/cendoj-status.md"
    )
