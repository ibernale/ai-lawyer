"""La Ley (Wolters Kluwer) source stub.

Status: ADR 0011 RED — blocked until a signed API contract with Wolters Kluwer exists.
See docs/legal/comerciales-status.md.

Do NOT implement any connectors until Santander Legal has signed an API agreement.
"""

from __future__ import annotations

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_RED_MSG = (
    "La Ley (Wolters Kluwer): ADR 0011 RED — requiere contrato API firmado "
    "por Santander Legal. Ver docs/legal/comerciales-status.md"
)


class LaLeySource(Source):
    """La Ley source — RED stub.

    All methods raise NotImplementedError.  No connector is implemented until
    Santander Legal provides a signed API agreement with Wolters Kluwer.
    See docs/legal/comerciales-status.md.
    """

    source_id = "laley"
    rate_limit_rps: float = 0.5

    async def list_documents(self) -> list[str]:
        raise NotImplementedError(_RED_MSG)

    async def fetch(self, doc_id: str) -> RawDocument:
        raise NotImplementedError(_RED_MSG)

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        raise NotImplementedError(_RED_MSG)
