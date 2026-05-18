"""CNMC (Comisión Nacional de Mercados y la Competencia) source.

Fetches resolutions and reports from the CNMC open-data portal.
Primary: REST/JSON API at https://www.cnmc.es/api/v1/resoluciones (checked 2026-05-18).
Fallback: HTML scraping of https://www.cnmc.es/expedientes.

Rate limit: 0.5 req/s.
Domain: administrativo, regulatorio_bancario_ue_es.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx
import structlog
from bs4 import BeautifulSoup

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.cnmc.es"
_JSON_API = f"{_BASE}/api/v1/resoluciones"
_HTML_LISTING = f"{_BASE}/expedientes"
_DATE_RE = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")


class CnmcSource(Source):
    """Source implementation for CNMC resolutions and reports."""

    source_id = "cnmc"
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Return CNMC document IDs (expediente codes).

        Tries JSON API first; falls back to HTML scraping.
        Returns a capped list of up to 50 IDs.
        """
        try:
            ids = await self._list_from_json()
            if ids:
                logger.info("cnmc.list_json", count=len(ids))
                return ids[:50]
        except Exception:
            logger.exception("cnmc.list_json_failed")

        try:
            ids = await self._list_from_html()
            logger.info("cnmc.list_html", count=len(ids))
            return ids[:50]
        except Exception:
            logger.exception("cnmc.list_html_failed")

        return []

    async def _list_from_json(self) -> list[str]:
        await self._rate_limiter.acquire()
        resp = await self._client.get(
            _JSON_API,
            params={"page": 0, "size": 50, "sort": "fechaResolucion,desc"},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("content", data.get("items", []))
        return [str(item.get("expediente") or item.get("id", "")) for item in items if item]

    async def _list_from_html(self) -> list[str]:
        await self._rate_limiter.acquire()
        resp = await self._client.get(_HTML_LISTING)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        ids: list[str] = []
        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            if "/expediente/" in href or "/resolucion/" in href:
                # Extract ID segment from URL
                segment = href.rstrip("/").split("/")[-1]
                if segment:
                    ids.append(segment)
        return list(dict.fromkeys(ids))  # deduplicate preserving order

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a CNMC document by expediente ID."""
        url = f"{_BASE}/expediente/{doc_id}"
        await self._rate_limiter.acquire()
        resp = await self._client.get(url)
        resp.raise_for_status()
        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=url,
            content_type="html",
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a CNMC HTML page into a CanonicalDocument."""
        soup = BeautifulSoup(raw.raw_bytes.decode("utf-8", errors="replace"), "html.parser")

        # Extract title
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        # Extract publication date
        pub_date: date = date.today()
        for tag in soup.find_all(string=_DATE_RE):
            m = _DATE_RE.search(str(tag))
            if m:
                try:
                    pub_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                    break
                except ValueError:
                    pass

        # Extract body text
        text_container = soup.find("article") or soup.find("main") or soup.find("body")
        full_text = text_container.get_text(separator="\n", strip=True) if text_container else ""

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="ES",
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            title=title,
            type="resolucion",
            publication_date=pub_date,
            status="vigente",
            full_text=full_text,
            domain="administrativo",
            hierarchy=[
                HierarchyNode(level="organismo", label="CNMC"),
            ],
        )
