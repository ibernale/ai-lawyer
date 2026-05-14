"""parse_canonical stub for SIDOF (Sistema de Información Documental y Oficial).

Implementation pending data access agreement.
SIDOF access requires agreement with data provider — Fase 10.
"""

from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SIDOF stub — not yet implemented."""
    return {
        **event,
        "status": "stub_not_implemented",
        "source": "sidof",
        "note": "SIDOF access requires agreement with data provider — Fase 10",
    }
