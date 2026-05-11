"""ESMA (European Securities and Markets Authority) Q&A source.

Fetches Q&A documents from:
  https://www.esma.europa.eu/publications-and-data/questions-and-answers

HTML listing with pagination; no public JSON API detected as of 2026-05-11.

Rate limit: 0.5 req/s (1 req / 2 s effective).
Domain: mercantil.
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
_BASE = "https://www.esma.europa.eu"
_LISTING = f"{_BASE}/publications-and-data/questions-and-answers"

_QA_ID_RE = re.compile(r"ESMA[\s\-/]*(\d{2,3}-\d{3,4}-\d{3,4}|\d{4,7})", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b")


class EsmaSource(Source):
    """Source implementation for ESMA Q&As."""

    source_id = "esma"
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

    async def list_documents(self) -> list[str]:
        """Scrape the ESMA Q&A listing with pagination and return document IDs."""
        doc_ids: list[str] = []
        page = 0

        while True:
            url = _LISTING if page == 0 else f"{_LISTING}?page={page}"
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("esma.list_fetch_error", url=url, error=str(exc))
                break

            soup = BeautifulSoup(resp.text, "lxml")
            found_on_page = 0

            for a_tag in soup.find_all("a", href=True):
                href: str = a_tag["href"]
                # Only follow Q&A-looking links
                if "question" not in href.lower() and "qa" not in href.lower():
                    continue
                text = a_tag.get_text(" ", strip=True)
                # Build stable ID from URL slug
                slug = href.rstrip("/").split("/")[-1]
                if not slug or len(slug) < 5:
                    continue

                # Try to extract ESMA reference number from text
                m = _QA_ID_RE.search(text)
                doc_id = f"ESMA-QA-{m.group(1).replace(' ', '-')}" if m else f"ESMA-QA-{slug}"
                if doc_id in doc_ids:
                    continue

                abs_href = href if href.startswith("http") else f"{_BASE}{href}"
                self._url_cache[doc_id] = abs_href
                doc_ids.append(doc_id)
                found_on_page += 1

            if found_on_page == 0:
                logger.info("esma.list_no_more_pages", page=page, total=len(doc_ids))
                break
            page += 1

        logger.info("esma.list_done", count=len(doc_ids))
        return doc_ids

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the Q&A page for the given ID."""
        url = self._url_cache.get(doc_id, _LISTING)

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("esma.fetch_failed", doc_id=doc_id, error=str(exc))
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
        """Extract Q&A metadata and text from the ESMA page."""
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

        # --- Metadata from structured page elements ---
        qa_id = ""
        topic = ""
        regulation_reference = ""

        for dl in soup.find_all("dl"):
            for dt in dl.find_all("dt"):
                label = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling("dd")
                value = dd.get_text(" ", strip=True) if dd else ""
                if "reference" in label or "esma" in label:
                    qa_id = value
                elif "topic" in label or "área" in label:
                    topic = value
                elif "regulation" in label or "reglamento" in label or "directive" in label:
                    regulation_reference = value

        # Fallback: extract Q&A reference from title
        if not qa_id:
            m = _QA_ID_RE.search(title)
            if m:
                qa_id = m.group(0)

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
            domain="mercantil",
            extra={
                "qa_id": qa_id,
                "topic": topic,
                "regulation_reference": regulation_reference,
            },
        )
