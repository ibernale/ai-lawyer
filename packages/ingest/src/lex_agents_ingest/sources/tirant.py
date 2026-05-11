"""Tirant lo Blanch source — prepared but disabled. ADR 0029.

Reference: docs/decisions/0029-adapters-comerciales-deshabilitados.md
See docs/legal/comerciales-status.md for license status.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument
from lex_agents_shared.exceptions import CommercialSourceDisabledError

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class TirantSource(Source):
    """Tirant lo Blanch source — disabled until license signed.

    All public methods are guarded by ``_require_license()``, which raises
    ``CommercialSourceDisabledError`` unless a *fixture_path* is provided
    (test mode). See ADR 0029 and docs/legal/comerciales-status.md.
    """

    source_id = "tirant"
    rate_limit_rps: float = 0.5
    _SOURCE_NAME = "tirant"

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__()
        self._fixture_path = fixture_path

    def _require_license(self) -> None:
        """Raise CommercialSourceDisabledError unless in fixture/test mode."""
        if self._fixture_path is not None:
            return  # test mode — bypass guard
        raise CommercialSourceDisabledError(self._SOURCE_NAME)

    async def list_documents(self, filters: dict | None = None) -> list[str]:  # type: ignore[override]
        """List available documents.

        Raises ``CommercialSourceDisabledError`` unless fixture mode.
        Real fetch logic skeleton — not yet implemented (license pending, ADR 0029).
        """
        self._require_license()
        return self._load_fixtures()

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a single document.

        Raises ``CommercialSourceDisabledError`` unless fixture mode.
        """
        self._require_license()
        assert self._fixture_path is not None
        fixture_file = self._fixture_path / f"{doc_id}.json"
        raw_bytes = fixture_file.read_bytes()
        from datetime import datetime, timezone
        return RawDocument(
            source="tirant",
            source_id=doc_id,
            raw_url=f"file://{fixture_file}",
            content_type="html",
            raw_bytes=raw_bytes,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a raw document.

        Raises ``CommercialSourceDisabledError`` unless fixture mode.
        """
        self._require_license()
        raise NotImplementedError(
            "Implement after license signed — see ADR 0029"
        )

    def _load_fixtures(self) -> list[str]:
        """Return fixture doc_ids for testing."""
        assert self._fixture_path is not None
        return [f.stem for f in self._fixture_path.glob("*.json")]
