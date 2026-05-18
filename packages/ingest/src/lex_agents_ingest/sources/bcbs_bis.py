"""BCBS/BIS (Basel Committee on Banking Supervision / Bank for International Settlements) source.

Fetches standards, consultative documents and working papers from
https://www.bis.org/bcbs/publications.htm.
Primary: HTML scraping of the BIS/BCBS publications listing.
Rate limit: 0.5 req/s.
Domain: regulatorio_bancario_ue_es.
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
_BASE = "https://www.bis.org"
_BCBS_LISTING = f"{_BASE}/bcbs/publications.htm"
_DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})")
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_DOC_TYPE_MAP = {
    "standard": "standard",
    "consultation": "consultative_document",
    "working paper": "working_paper",
    "guidance": "guidance",
    "newsletter": "newsletter",
    "report": "report",
}


def _infer_type(text: str) -> str:
    lower = text.lower()
    for key, val in _DOC_TYPE_MAP.items():
        if key in lower:
            return val
    return "document"


def _parse_date(text: str) -> date | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


class BcbsBisSource(Source):
    """Source implementation for BIS/BCBS publications."""

    source_id = "bcbs_bis"
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Return absolute BIS document URLs as document IDs (capped at 50)."""
        try:
            await self._rate_limiter.acquire()
            resp = await self._client.get(_BCBS_LISTING)
            resp.raise_for_status()
        except Exception:
            logger.exception("bcbs_bis.list_failed")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        doc_urls: list[str] = []
        seen: set[str] = set()

        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            # BIS publications are typically at /publ/<id>.htm or /bcbs/<id>.pdf
            if re.search(r"/publ/[a-z0-9]+\.(htm|pdf)$", href) or re.search(r"/bcbs/[a-z0-9_]+\.(htm|pdf)$", href):
                full = href if href.startswith("http") else _BASE + href
                if full not in seen:
                    seen.add(full)
                    doc_urls.append(full)

        logger.info("bcbs_bis.list", count=len(doc_urls))
        return doc_urls[:50]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a BIS document by URL."""
        await self._rate_limiter.acquire()
        resp = await self._client.get(doc_id)
        resp.raise_for_status()
        content_type = "pdf" if doc_id.endswith(".pdf") else "html"
        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=doc_id,
            content_type=content_type,
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a BIS HTML page or PDF stub into a CanonicalDocument."""
        if raw.content_type == "pdf":
            return CanonicalDocument(
                source=self.source_id,
                source_id=raw.source_id,
                jurisdiction="GLOBAL",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                title=raw.source_id.split("/")[-1].replace("-", " "),
                type="document",
                status="final",
                full_text="",
                domain="regulatorio_bancario_ue_es",
                hierarchy=[
                    HierarchyNode(level="organismo", label="BCBS/BIS"),
                ],
            )

        soup = BeautifulSoup(raw.raw_bytes.decode("utf-8", errors="replace"), "html.parser")

        title = ""
        h1 = soup.find("h1") or soup.find("h2")
        if h1:
            title = h1.get_text(strip=True)

        pub_date: date = date.today()
        parsed = _parse_date(soup.get_text())
        if parsed:
            pub_date = parsed

        # Determine if final standard or consultative
        text_lower = (title + " " + soup.get_text()[:500]).lower()
        doc_type = _infer_type(text_lower)
        status = "consultiva" if "consult" in text_lower else "final"

        full_text = ""
        for container in ("article", "main", "#content", ".content"):
            el = soup.find(container) if not container.startswith(("#", ".")) else soup.select_one(container)
            if el:
                full_text = el.get_text(separator="\n", strip=True)
                break
        if not full_text:
            full_text = soup.get_text(separator="\n", strip=True)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="GLOBAL",
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            title=title,
            type=doc_type,
            publication_date=pub_date,
            status=status,
            full_text=full_text,
            domain="regulatorio_bancario_ue_es",
            hierarchy=[
                HierarchyNode(level="organismo", label="BCBS/BIS"),
            ],
        )
