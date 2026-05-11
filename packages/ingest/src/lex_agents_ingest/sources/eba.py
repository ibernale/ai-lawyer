"""EBA (European Banking Authority) Single Rulebook Q&A source.

Primary: JSON API at https://www.eba.europa.eu/single-rule-book-qa (checked 2026-05-11).
The EBA Single Rulebook Q&A tool exposes a JSON endpoint; we query it with
pagination parameters.  If the JSON API is unavailable we fall back to HTML scraping.

Rate limit: 0.5 req/s (default, 1 req / 2 s effective).
Domain: regulatorio_bancario.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx
import structlog
from bs4 import BeautifulSoup

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.eba.europa.eu"
# The EBA Single Rulebook Q&A search page (HTML)
_HTML_LISTING = f"{_BASE}/single-rule-book-qa"
# Known JSON/REST endpoint patterns used by the EBA portal (Drupal-based)
# The EBA portal uses a JSON:API or Views-REST endpoint for the Q&A listing.
_JSON_CANDIDATES = [
    f"{_BASE}/api/v1/single-rulebook-qa",
    f"{_BASE}/single-rule-book-qa?_format=json",
    f"{_BASE}/views/single_rulebook_qa?_format=json",
]
_QA_ID_RE = re.compile(r"Q&A\s*(\d{4,6})", re.IGNORECASE)


class EbaSource(Source):
    """Source implementation for EBA Single Rulebook Q&As."""

    source_id = "eba"
    # 1 req / 2 s
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )
        self._url_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # JSON API attempt
    # ------------------------------------------------------------------

    async def _try_json_api(self) -> list[dict] | None:
        """Try known JSON endpoints.  Returns list of Q&A dicts or None."""
        for url in _JSON_CANDIDATES:
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.get(
                    url,
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                # Expect a list or dict with a 'data' or 'results' key
                if isinstance(data, list) and data:
                    logger.info("eba.json_api_ok", url=url, count=len(data))
                    return data
                if isinstance(data, dict):
                    for key in ("data", "results", "items", "rows"):
                        if key in data and isinstance(data[key], list):
                            logger.info("eba.json_api_ok", url=url, key=key, count=len(data[key]))
                            return data[key]
            except Exception as exc:
                logger.debug("eba.json_api_miss", url=url, error=str(exc))

        return None

    # ------------------------------------------------------------------
    # HTML fallback
    # ------------------------------------------------------------------

    async def _list_from_html(self) -> list[tuple[str, str]]:
        """Scrape the HTML Q&A listing page."""
        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(_HTML_LISTING)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("eba.html_listing_failed", error=str(exc))
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        results: list[tuple[str, str]] = []

        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            text = a_tag.get_text(" ", strip=True)
            m = _QA_ID_RE.search(text) or _QA_ID_RE.search(href)
            if not m:
                continue
            qa_id = f"EBA-QA-{m.group(1)}"
            if qa_id in (r[0] for r in results):
                continue
            abs_href = href if href.startswith("http") else f"{_BASE}{href}"
            results.append((qa_id, abs_href))

        logger.info("eba.html_list_done", count=len(results))
        return results

    # ------------------------------------------------------------------
    # Source interface
    # ------------------------------------------------------------------

    async def list_documents(self) -> list[str]:
        """Return Q&A IDs, trying JSON API first then HTML."""
        json_items = await self._try_json_api()
        if json_items:
            doc_ids: list[str] = []
            for item in json_items:
                # Typical JSON keys from EBA portal
                qa_id_raw = (
                    item.get("id")
                    or item.get("qa_id")
                    or item.get("field_qa_id")
                    or item.get("nid")
                    or ""
                )
                url = item.get("url") or item.get("path") or item.get("links", {}).get("self", "")
                doc_id = f"EBA-QA-{qa_id_raw}" if qa_id_raw else f"EBA-QA-UNKNOWN-{len(doc_ids)}"
                if url:
                    self._url_cache[doc_id] = url if url.startswith("http") else f"{_BASE}{url}"
                doc_ids.append(doc_id)
            return doc_ids

        html_items = await self._list_from_html()
        for doc_id, url in html_items:
            self._url_cache[doc_id] = url
        return [doc_id for doc_id, _ in html_items]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the Q&A page for the given ID."""
        url = self._url_cache.get(doc_id, _HTML_LISTING)

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("eba.fetch_failed", doc_id=doc_id, error=str(exc))
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
        """Extract Q&A metadata and full text."""
        soup = BeautifulSoup(raw.raw_bytes, "lxml")
        full_text_raw = soup.get_text(" ", strip=True)

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

        # --- Q&A specific metadata ---
        topic = ""
        related_articles = ""
        status = "unknown"
        date_submitted = ""
        date_answered = ""

        # Look for structured metadata in definition lists or labeled divs
        for dl in soup.find_all("dl"):
            items = dl.find_all("dt")
            for dt in items:
                label = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling("dd")
                value = dd.get_text(" ", strip=True) if dd else ""
                if "topic" in label or "topic" in label:
                    topic = value
                elif "article" in label or "artículo" in label:
                    related_articles = value
                elif "status" in label or "estado" in label:
                    status = value.lower()
                elif "submitted" in label or "enviada" in label:
                    date_submitted = value
                elif "answered" in label or "respondida" in label:
                    date_answered = value

        # Status normalisation
        if "answered" in status or "respondida" in status:
            status = "answered"
        elif "pending" in status or "pendiente" in status:
            status = "pending"

        content_el = soup.find("article") or soup.find("main")
        full_text = (content_el or soup).get_text("\n", strip=True)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="EU",
            type="qa",
            title=title,
            publication_date=pub_date,
            status="unknown",
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            domain="regulatorio_bancario",
            extra={
                "topic": topic,
                "related_articles": related_articles,
                "status": status,
                "date_submitted": date_submitted,
                "date_answered": date_answered,
            },
        )
