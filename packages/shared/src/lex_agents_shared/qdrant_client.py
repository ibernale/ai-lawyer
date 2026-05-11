"""Qdrant client wrapper with healthcheck and factory helper."""

from __future__ import annotations

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class QdrantClientWrapper:
    """Thin wrapper around `QdrantClient` with healthcheck support.

    Usage::

        wrapper = QdrantClientWrapper.from_config(url="http://localhost:6333")
        ok = wrapper.ping()
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        url: str,
        api_key: str | None = None,
        timeout: float = 10.0,
    ) -> QdrantClientWrapper:
        client = QdrantClient(url=url, api_key=api_key or None, timeout=int(timeout))
        return cls(client)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if Qdrant responds to a health probe."""
        try:
            self._client.get_collections()
            return True
        except (UnexpectedResponse, ConnectionError, OSError) as exc:
            logger.warning("qdrant_ping_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Delegate
    # ------------------------------------------------------------------

    @property
    def client(self) -> QdrantClient:
        """Underlying QdrantClient for direct use in packages/rag."""
        return self._client

    def close(self) -> None:
        self._client.close()
