"""Aranzadi (Thomson Reuters) source stub.

Status: ADR 0011 RED — blocked until a signed API contract with Thomson Reuters exists.
See docs/legal/comerciales-status.md.

Do NOT implement any connectors until Santander Legal has signed an API agreement.
Creating technical infrastructure for licensed content without a contract creates
legal exposure independently of whether the connector is used in production.
"""

from __future__ import annotations

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_RED_MSG = (
    "Aranzadi (Thomson Reuters): ADR 0011 RED — requiere contrato API firmado "
    "por Santander Legal. Ver docs/legal/comerciales-status.md"
)


class AranzadiSource(Source):
    """Aranzadi source — RED stub.

    All methods raise NotImplementedError.  No connector is implemented until
    Santander Legal provides a signed API agreement with Thomson Reuters.
    See docs/legal/comerciales-status.md.
    """

    source_id = "aranzadi"
    rate_limit_rps: float = 0.5

    async def list_documents(self) -> list[str]:
        raise NotImplementedError(_RED_MSG)

    async def fetch(self, doc_id: str) -> RawDocument:
        raise NotImplementedError(_RED_MSG)

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        raise NotImplementedError(_RED_MSG)
