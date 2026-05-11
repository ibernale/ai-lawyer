"""Abstract base for legal document sources with rate limiting."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

import anyio
import structlog

from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class RateLimiter:
    """Token-bucket rate limiter (per-source, in-process).

    Ensures at most *rps* calls per second using anyio sleep.
    """

    def __init__(self, rps: float = 0.5) -> None:
        self._interval = 1.0 / rps
        self._last: float = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        wait = self._interval - (now - self._last)
        if wait > 0:
            await anyio.sleep(wait)
        self._last = time.monotonic()


class Source(ABC):
    """Interface every legal document source must implement."""

    source_id: str
    rate_limit_rps: float = 0.5

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter(self.rate_limit_rps)

    @abstractmethod
    async def list_documents(self) -> list[str]:
        """Return a list of document IDs available from this source."""
        ...

    @abstractmethod
    async def fetch(self, doc_id: str) -> RawDocument:
        """Download *doc_id* and return its bytes wrapped in RawDocument."""
        ...

    @abstractmethod
    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a RawDocument into a CanonicalDocument."""
        ...

    async def fetch_and_parse(self, doc_id: str) -> CanonicalDocument:
        """Rate-limited fetch + parse convenience method."""
        await self._rate_limiter.acquire()
        raw = await self.fetch(doc_id)
        return self.parse_to_canonical(raw)
