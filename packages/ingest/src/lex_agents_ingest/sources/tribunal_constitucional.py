"""Tribunal Constitucional (TC) source stub.

Status: ADR 0011 AMBER — blocked until terms-of-use verification.
See docs/legal/cendoj-status.md for the unlock process.

Do not implement until Legal del Grupo confirms that TC terms of use permit
automated bulk access.
"""

from __future__ import annotations

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_AMBER_MSG = (
    "TC: ADR 0011 AMBER — pendiente verificación de términos de uso. "
    "Ver docs/legal/cendoj-status.md"
)


class TribunalConstitucionalSource(Source):
    """Tribunal Constitucional source — AMBER stub.

    All methods raise NotImplementedError until Legal del Grupo confirms that
    TC terms of use permit automated access.  See docs/legal/cendoj-status.md.
    """

    source_id = "tribunal_constitucional"
    rate_limit_rps: float = 0.5

    async def list_documents(self) -> list[str]:
        raise NotImplementedError(_AMBER_MSG)

    async def fetch(self, doc_id: str) -> RawDocument:
        raise NotImplementedError(_AMBER_MSG)

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        raise NotImplementedError(_AMBER_MSG)
