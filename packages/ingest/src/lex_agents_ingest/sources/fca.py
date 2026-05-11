"""FCA (Financial Conduct Authority) Handbook source.

# FCA Handbook has no public XML API as of 2026-05; HTML scraping only. Coverage is partial.

Covered sections (minimum required):
  - PRIN — Principles for Businesses
  - COBS — Conduct of Business Sourcebook
  - SYSC — Senior Management Arrangements, Systems and Controls

Each section is fetched as HTML from:
  https://www.handbook.fca.org.uk/handbook/<section>

Domain: regulatorio_bancario.
Jurisdiction: GB.
Rate limit: 0.5 req/s.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx
import structlog
from bs4 import BeautifulSoup

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.handbook.fca.org.uk"

# Covered sections: (section_code, url_path, human_title)
COVERED_SECTIONS: list[tuple[str, str, str]] = [
    ("PRIN", "/handbook/PRIN", "Principles for Businesses"),
    ("COBS", "/handbook/COBS", "Conduct of Business Sourcebook"),
    ("SYSC", "/handbook/SYSC", "Senior Management Arrangements, Systems and Controls"),
]

_CHAPTER_RE = re.compile(r"^(\d+)$")
_RULE_RE = re.compile(r"^(\d+\.\d+)$")


class FcaSource(Source):
    """Source implementation for FCA Handbook sections (HTML scraping only).

    Note: The FCA Handbook site is a complex JavaScript-rendered portal.
    This implementation fetches the static HTML TOC pages and individual
    chapter/chapter-annex pages.  Some content may require JavaScript
    rendering for complete extraction; those pages will have reduced text.
    """

    source_id = "fca"
    # 0.5 req/s (1 req / 2 s)
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )
        # Maps doc_id → url
        self._url_cache: dict[str, str] = {
            code: f"{_BASE}{path}" for code, path, _ in COVERED_SECTIONS
        }
        self._section_meta: dict[str, str] = {
            code: title for code, _, title in COVERED_SECTIONS
        }

    async def list_documents(self) -> list[str]:
        """Return one document ID per covered section, plus chapter-level IDs.

        For each top-level section we also scrape the TOC to discover chapters.
        """
        doc_ids: list[str] = list(self._url_cache.keys())

        for section_code, path, _ in COVERED_SECTIONS:
            toc_url = f"{_BASE}{path}"
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.get(toc_url)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("fca.toc_fetch_failed", section=section_code, error=str(exc))
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            for a_tag in soup.find_all("a", href=True):
                href: str = a_tag["href"]
                # Chapter links look like /handbook/PRIN/1 or /handbook/COBS/2
                if not href.startswith(path + "/"):
                    continue
                chapter_suffix = href[len(path) + 1:].split("/")[0]
                if not chapter_suffix or not chapter_suffix[0].isdigit():
                    continue
                chapter_id = f"{section_code}/{chapter_suffix}"
                if chapter_id not in doc_ids:
                    abs_href = href if href.startswith("http") else f"{_BASE}{href}"
                    self._url_cache[chapter_id] = abs_href
                    doc_ids.append(chapter_id)

        return doc_ids

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the FCA Handbook page for the given section/chapter ID."""
        url = self._url_cache.get(doc_id)
        if not url:
            # Best-effort: reconstruct URL
            url = f"{_BASE}/handbook/{doc_id}"

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("fca.fetch_failed", doc_id=doc_id, url=url, error=str(exc))
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
        """Parse a FCA Handbook HTML page into a CanonicalDocument."""
        soup = BeautifulSoup(raw.raw_bytes, "lxml")

        # --- Title ---
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        if not title:
            # Fallback to section meta
            section_code = raw.source_id.split("/")[0]
            title = self._section_meta.get(section_code, raw.source_id)

        # --- Date: FCA doesn't embed explicit dates in HTML; use today as fallback ---
        pub_date = datetime.utcnow().date()
        # Try to find a "last updated" annotation
        for pattern in (
            soup.find("span", string=re.compile(r"last updated", re.I)),
            soup.find("time"),
        ):
            if pattern:
                dt_str = (
                    pattern.get("datetime", "")
                    if pattern.name == "time"
                    else pattern.get_text(strip=True)
                )
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y"):
                    try:
                        pub_date = datetime.strptime(dt_str[:len(fmt)], fmt).date()
                        break
                    except (ValueError, TypeError):
                        continue
                break

        # --- Hierarchy: rules appear as h2/h3 with rule numbers ---
        hierarchy: list[HierarchyNode] = []
        texts: list[str] = []

        content_el = (
            soup.find("div", class_=re.compile(r"(content|handbook|rules)", re.I))
            or soup.find("article")
            or soup.find("main")
        )
        container = content_el or soup

        for heading in container.find_all(re.compile(r"^h[2-4]$")):
            heading_text = heading.get_text(" ", strip=True)
            # Try to identify rule number (e.g. "2.1" or "PRIN 1.1")
            m = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", heading_text)
            rule_num = m.group(1) if m else ""
            hierarchy.append(
                HierarchyNode(level="articulo", number=rule_num, title=heading_text)
            )
            # Collect text following this heading until the next heading
            sibling = heading.find_next_sibling()
            para_texts = []
            while sibling and sibling.name not in ("h2", "h3", "h4"):
                para_texts.append(sibling.get_text(" ", strip=True))
                sibling = sibling.find_next_sibling()
            if para_texts:
                texts.append("\n".join(para_texts))

        full_text = "\n\n".join(texts) if texts else container.get_text("\n", strip=True)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="GB",
            type="other",
            title=title,
            publication_date=pub_date,
            status="vigente",
            hierarchy=hierarchy,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            domain="regulatorio_bancario",
            extra={"section": raw.source_id.split("/")[0]},
        )
