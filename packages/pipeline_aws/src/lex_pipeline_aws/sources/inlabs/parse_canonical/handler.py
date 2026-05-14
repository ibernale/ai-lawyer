"""parse_canonical stub for INLABS (Imprensa Nacional Brasil).

Implementation pending data access agreement.
INLABS access requires OIDC token from Imprensa Nacional — Fase 10.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """INLABS stub — not yet implemented."""
    return {
        **event,
        "status": "stub_not_implemented",
        "source": "inlabs",
        "note": "INLABS access requires OIDC token from Imprensa Nacional — Fase 10",
    }
