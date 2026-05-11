"""CENDOJ (Centro de Documentación Judicial) source stubs.

Status: ADR 0011 AMBER — blocked until CGPJ authorisation.
See docs/legal/cendoj-status.md for the unlock process.

Two classes are provided:

  CendojSource — full implementation stub (always raises NotImplementedError).
  CendojPuntualSource — DEV ONLY, enabled via CENDOJ_DEV_MODE=true environment
      variable.  Rate limited to ≤50 requests / day, with asyncio.sleep(5) between
      requests.  Never activates in production.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_AMBER_MSG = (
    "CENDOJ: ADR 0011 AMBER — pendiente autorización CGPJ. "
    "Ver docs/legal/cendoj-status.md"
)
_DEV_COUNTER_FILE = Path("/tmp/cendoj_puntual_counter.json")
_MAX_DAILY_REQUESTS = 50


class CendojSource(Source):
    """CENDOJ bulk source — AMBER stub, always raises NotImplementedError.

    Do not use in production until authorisation from CGPJ has been obtained.
    See docs/legal/cendoj-status.md.
    """

    source_id = "cendoj"
    rate_limit_rps: float = 0.5

    async def list_documents(self) -> list[str]:
        raise NotImplementedError(_AMBER_MSG)

    async def fetch(self, doc_id: str) -> RawDocument:
        raise NotImplementedError(_AMBER_MSG)

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        raise NotImplementedError(_AMBER_MSG)


# ---------------------------------------------------------------------------
# Dev-mode point query (≤50 req/day)
# ---------------------------------------------------------------------------

def _load_counter() -> dict:
    if _DEV_COUNTER_FILE.exists():
        try:
            return json.loads(_DEV_COUNTER_FILE.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"date": "", "count": 0}


def _save_counter(data: dict) -> None:
    try:
        _DEV_COUNTER_FILE.write_text(json.dumps(data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cendoj_puntual.counter_save_failed", error=str(exc))


def _check_and_increment() -> None:
    """Raise RuntimeError if daily limit exceeded; otherwise increment counter."""
    today = datetime.utcnow().date().isoformat()
    data = _load_counter()
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    if data["count"] >= _MAX_DAILY_REQUESTS:
        raise RuntimeError(
            f"CENDOJ_DEV_MODE: daily limit of {_MAX_DAILY_REQUESTS} requests reached. "
            "Reset at midnight UTC."
        )
    data["count"] += 1
    _save_counter(data)


class CendojPuntualSource(Source):
    """CENDOJ point-query source for DEVELOPMENT ONLY.

    Enabled only when the environment variable CENDOJ_DEV_MODE is set to "true".
    Hard rate limit: ≤50 requests / day (persisted in /tmp/cendoj_puntual_counter.json).
    asyncio.sleep(5) between every request.

    NEVER activate in production without CGPJ authorisation.
    See docs/legal/cendoj-status.md.
    """

    source_id = "cendoj_puntual"
    # asyncio.sleep(5) is applied explicitly in each method; RateLimiter also active.
    rate_limit_rps: float = 0.2  # 1 req / 5 s via RateLimiter

    _BASE_SEARCH = "https://www.poderjudicial.es/search/AN/openCriteria/"
    _BASE_DOC = "https://www.poderjudicial.es/search/AN/openDocument/"

    def __init__(self) -> None:
        if os.environ.get("CENDOJ_DEV_MODE") != "true":
            raise RuntimeError("CENDOJ_DEV_MODE disabled")
        import httpx
        super().__init__()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"},
            follow_redirects=True,
            timeout=30.0,
        )
        logger.warning(
            "cendoj_puntual.dev_mode_active",
            warning="CENDOJ_DEV_MODE is active. Max 50 req/day. Never use in production.",
        )

    async def list_documents(self) -> list[str]:
        """Return a short sample of recent CENDOJ document IDs (dev only)."""
        _check_and_increment()
        await asyncio.sleep(5)
        import httpx

        # The CENDOJ public search has changed over time; we use a basic GET
        # against the open-data endpoint with a generic recent-date filter.
        url = f"{self._BASE_SEARCH}?offset=0&nres=10"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("cendoj_puntual.list_failed", error=str(exc))
            return []

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.content, "lxml")
        doc_ids: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if "openDocument" in href:
                slug = href.rstrip("/").split("/")[-1]
                if slug:
                    doc_ids.append(f"CENDOJ-{slug}")
        return doc_ids[:10]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download a CENDOJ document by ID (dev only)."""
        _check_and_increment()
        await asyncio.sleep(5)

        slug = doc_id.replace("CENDOJ-", "")
        url = f"{self._BASE_DOC}{slug}"
        resp = await self._client.get(url)
        resp.raise_for_status()

        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="html",
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:  # type: ignore[override]
        """Minimal parse of a CENDOJ HTML page (dev only)."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw.raw_bytes, "lxml")
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        full_text = soup.get_text("\n", strip=True)

        # CanonicalDocument does not currently list "cendoj_puntual" as a valid source.
        # We store under a placeholder source while in dev mode.
        # This will be updated when AMBER → GREEN.
        # NOTE: this bypasses the strict Literal validation; mypy will flag it.
        return CanonicalDocument.model_construct(  # type: ignore[call-arg]
            source="cendoj_puntual",
            source_id=raw.source_id,
            jurisdiction="ES",
            type="other",
            title=title,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            status="unknown",
            domain="jurisprudencia_es",
        )
