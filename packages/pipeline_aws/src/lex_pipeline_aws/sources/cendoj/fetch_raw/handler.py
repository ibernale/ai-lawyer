"""fetch_raw handler for CENDOJ — Lambda step in ingest_cendoj state machine.

AMBER source — schedule disabled by default.
Status: ADR 0011 AMBER — blocked until CGPJ authorisation.
See docs/legal/cendoj-status.md for the unlock process.

CendojSource.list_documents() always raises NotImplementedError.
This handler propagates that error to prevent accidental activation.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AMBER source — raises NotImplementedError until CGPJ authorisation obtained."""
    # AMBER source — schedule disabled by default
    # Do not activate without CGPJ authorisation (see docs/legal/cendoj-status.md)
    raise NotImplementedError(
        "CENDOJ: ADR 0011 AMBER — pendiente autorización CGPJ. "
        "Ver docs/legal/cendoj-status.md"
    )
