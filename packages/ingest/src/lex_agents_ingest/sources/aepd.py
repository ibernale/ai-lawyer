"""AEPD (Agencia Española de Protección de Datos) resolution source.

Scrapes the public resolution search page at:
  https://www.aepd.es/es/resoluciones-y-actuaciones/resoluciones

No public XML/JSON API exists as of 2026-05; HTML scraping only.
Rate limit: 1 req / 3 s (asyncio.sleep via RateLimiter).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx
import structlog
from bs4 import BeautifulSoup

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.aepd.es"
_LISTING = f"{_BASE}/es/resoluciones-y-actuaciones/resoluciones"
# Resolutions are served as individual pages; the search listing shows paginated
# results.  The URL pattern for individual resolutions is:
#   https://www.aepd.es/es/documento/PS-XXXXX-YYYY.pdf   (PDF canonical link)
# but the HTML page is accessible at:
#   https://www.aepd.es/es/documento/<slug>
# We identify resolutions by their procedimiento number, e.g. PS/00001/2024.
_PROC_RE = re.compile(r"PS[/\-]\d{5}[/\-]\d{4}", re.IGNORECASE)
_SANCTION_RE = re.compile(
    r"multa\s+de\s+([\d\.,]+)\s*euros?|sanción\s+de\s+([\d\.,]+)\s*euros?",
    re.IGNORECASE,
)


class AepdSource(Source):
    """Source implementation for AEPD resoluciones (HTML scraping)."""

    source_id = "aepd"
    # 1 req / 3 s
    rate_limit_rps: float = 1.0 / 3.0

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Fetch the search listing and return up to 50 most-recent resolution IDs.

        Resolution IDs use the procedimiento format: PS/XXXXX/YYYY.
        """
        doc_ids: list[str] = []
        page = 0

        while len(doc_ids) < 50:
            url = _LISTING if page == 0 else f"{_LISTING}?page={page}"
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("aepd.list_http_error", url=url, status=exc.response.status_code)
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("aepd.list_fetch_error", url=url, error=str(exc))
                break

            soup = BeautifulSoup(resp.text, "lxml")
            # Resolution links appear inside <a> tags whose href contains "/documento/"
            found_on_page = 0
            for a_tag in soup.find_all("a", href=True):
                href: str = a_tag["href"]
                # Match procedimiento numbers in link text or href
                text = a_tag.get_text(" ", strip=True)
                match = _PROC_RE.search(text) or _PROC_RE.search(href)
                if match:
                    proc_id = match.group(0).upper().replace("-", "/")
                    if proc_id not in doc_ids:
                        doc_ids.append(proc_id)
                        found_on_page += 1

            if found_on_page == 0:
                # No more pages or pattern has changed
                logger.info("aepd.list_no_more_pages", page=page, total=len(doc_ids))
                break

            page += 1

        logger.info("aepd.list_done", count=len(doc_ids))
        return doc_ids[:50]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the resolution HTML page for the given procedimiento ID."""
        # Derive slug: PS/00001/2024 → PS-00001-2024
        slug = doc_id.replace("/", "-")
        url = f"{_BASE}/es/documento/{slug}"

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "aepd.fetch_http_error", doc_id=doc_id, status=exc.response.status_code
            )
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
        """Extract title, date, resolution type, sanction amount, and full text."""
        soup = BeautifulSoup(raw.raw_bytes, "lxml")

        # --- Title ---
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "").strip()

        # --- Date ---
        pub_date = datetime.utcnow().date()
        # Look for <time> element or common date patterns in the page
        time_el = soup.find("time")
        if time_el:
            dt_str = time_el.get("datetime", "") or time_el.get_text(strip=True)
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    pub_date = datetime.strptime(dt_str[:10], fmt).date()
                    break
                except ValueError:
                    continue

        # --- Resolution type (sancionadora / tutela / informe) ---
        full_text_raw = soup.get_text(" ", strip=True)
        resolution_type = "resolución"
        lower_text = full_text_raw.lower()
        if "procedimiento sancionador" in lower_text:
            resolution_type = "sancionadora"
        elif "reclamación" in lower_text:
            resolution_type = "tutela"
        elif "informe" in lower_text and "apd" in lower_text:
            resolution_type = "informe"

        # --- Sanction amount ---
        sanction_amount: str = ""
        sanction_match = _SANCTION_RE.search(full_text_raw)
        if sanction_match:
            sanction_amount = sanction_match.group(1) or sanction_match.group(2) or ""

        # --- Main content ---
        # Try to extract just the article / main content block
        content_el = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=re.compile(r"(content|body|text|resoluc)", re.I))
        )
        full_text = (content_el or soup).get_text("\n", strip=True)

        extra: dict[str, str] = {
            "resolution_type": resolution_type,
        }
        if sanction_amount:
            extra["sanction_amount_eur"] = sanction_amount

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="ES",
            type="resolution",
            title=title,
            publication_date=pub_date,
            status="unknown",
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            domain="datos_personales",
            extra=extra,
        )
