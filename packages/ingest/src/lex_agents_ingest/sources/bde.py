"""BdE (Banco de España) Circulares source.

Primary: RSS feed at https://www.bde.es/wbe/es/normativa/circulares-otra-normativa/
Fallback: HTML listing of the same page.

Rate limit: 1 req / 2 s.
Metadata captured: circular_number, year, subject, normas_modificadas.
Domain: regulatorio_bancario.
"""

from __future__ import annotations

import re
from datetime import datetime
from xml.etree import ElementTree as ET

import httpx
import structlog
from bs4 import BeautifulSoup

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.bde.es"
_LISTING_URL = f"{_BASE}/wbe/es/normativa/circulares-otra-normativa/"
# BdE doesn't publish a standard RSS for circulares, but some BdE pages expose Atom/RSS.
# We try a known RSS URL first; if it fails we fall back to HTML.
_RSS_CANDIDATES = [
    f"{_BASE}/wbe/es/normativa/circulares-otra-normativa/rss.xml",
    f"{_BASE}/wbe/rss/normativa/circulares.xml",
]

_CIRCULAR_RE = re.compile(r"Circular\s+(\d+/\d{4})", re.IGNORECASE)
_NORMAS_RE = re.compile(r"(modifica|deroga|complementa)[^.]*?(Circular[^.]+\.)", re.IGNORECASE)


class BdeSource(Source):
    """Source implementation for BdE Circulares."""

    source_id = "bde"
    # 1 req / 2 s
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )
        # Maps circular_id → page URL
        self._url_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # RSS helpers
    # ------------------------------------------------------------------

    async def _try_rss(self) -> list[tuple[str, str]]:
        """Try to fetch BdE circulares via RSS.  Returns list of (id, url) tuples."""
        for rss_url in _RSS_CANDIDATES:
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.get(rss_url)
                resp.raise_for_status()
            except Exception:
                continue

            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                continue

            # Handle both RSS 2.0 (<channel><item>) and Atom (<entry>)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)
            results: list[tuple[str, str]] = []
            for item in items:
                link_el = item.find("link") or item.find("atom:link", ns)
                title_el = item.find("title") or item.find("atom:title", ns)
                link = (link_el.text or link_el.get("href", "")).strip() if link_el is not None else ""
                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                m = _CIRCULAR_RE.search(title)
                if m:
                    doc_id = f"BDE-CIRC-{m.group(1).replace('/', '-')}"
                    results.append((doc_id, link))
            if results:
                logger.info("bde.rss_ok", url=rss_url, count=len(results))
                return results

        logger.info("bde.rss_failed; falling back to HTML listing")
        return []

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    async def _list_from_html(self) -> list[tuple[str, str]]:
        """Scrape the HTML listing page and return (id, url) tuples."""
        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(_LISTING_URL)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("bde.html_listing_failed", error=str(exc))
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results: list[tuple[str, str]] = []

        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(" ", strip=True)
            m = _CIRCULAR_RE.search(text)
            if m:
                href: str = a_tag["href"]
                abs_href = href if href.startswith("http") else f"{_BASE}{href}"
                doc_id = f"BDE-CIRC-{m.group(1).replace('/', '-')}"
                if doc_id not in (r[0] for r in results):
                    results.append((doc_id, abs_href))

        logger.info("bde.html_list_done", count=len(results))
        return results

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    async def list_documents(self) -> list[str]:
        """Return circular IDs, trying RSS first then HTML."""
        items = await self._try_rss()
        if not items:
            items = await self._list_from_html()

        for doc_id, url in items:
            self._url_cache[doc_id] = url

        return [doc_id for doc_id, _ in items]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the circular page (HTML) for the given ID."""
        url = self._url_cache.get(doc_id, _LISTING_URL)

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("bde.fetch_failed", doc_id=doc_id, url=url, error=str(exc))
            raise

        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="html",
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a BdE circular page into a CanonicalDocument."""
        soup = BeautifulSoup(raw.raw_bytes, "lxml")

        # --- Title ---
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)

        # --- Date ---
        pub_date = datetime.utcnow().date()
        time_el = soup.find("time")
        if time_el:
            dt_str = time_el.get("datetime", "") or time_el.get_text(strip=True)
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    pub_date = datetime.strptime(dt_str[:10], fmt).date()
                    break
                except ValueError:
                    continue

        full_text_raw = soup.get_text(" ", strip=True)

        # --- Circular number & year from doc_id ---
        # doc_id format: BDE-CIRC-N-YYYY
        circular_number = ""
        year = ""
        parts = raw.source_id.replace("BDE-CIRC-", "").split("-")
        if len(parts) == 2:
            circular_number = parts[0]
            year = parts[1]

        # --- Normas modificadas ---
        normas_modificadas = ""
        nm_match = _NORMAS_RE.search(full_text_raw)
        if nm_match:
            normas_modificadas = nm_match.group(0).strip()

        # --- Subject: first sentence after title ---
        subject = ""
        content_el = soup.find("article") or soup.find("main")
        if content_el:
            paras = content_el.find_all("p")
            for p in paras:
                txt = p.get_text(" ", strip=True)
                if txt and len(txt) > 20:
                    subject = txt[:512]
                    break

        full_text = (content_el or soup).get_text("\n", strip=True)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="ES",
            type="circular",
            title=title,
            publication_date=pub_date,
            status="unknown",
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            domain="regulatorio_bancario",
            extra={
                "circular_number": circular_number,
                "year": year,
                "subject": subject,
                "normas_modificadas": normas_modificadas,
            },
        )
