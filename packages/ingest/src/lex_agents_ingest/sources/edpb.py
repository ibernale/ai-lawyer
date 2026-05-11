"""EDPB (European Data Protection Board) document source.

Fetches Guidelines and Opinions from:
  https://www.edpb.europa.eu/our-work-tools/our-documents_en

Documents are published as PDFs.  EDPB is an explicit exception to the no-PDF
rule per ADR 0011 — its PDFs have a consistent machine-readable structure
parseable with pdfminer.six.

Rate limit: 1 req / 2 s.
"""

from __future__ import annotations

import io
from datetime import datetime

import httpx
import structlog
from bs4 import BeautifulSoup

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.edpb.europa.eu"
_LISTING = f"{_BASE}/our-work-tools/our-documents_en"

# Filter for Guidelines and Opinions only
_RELEVANT_TYPES = frozenset({"guideline", "guidelines", "opinion", "opinions"})


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfminer.six if available."""
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams

        output = io.StringIO()
        extract_text_to_fp(
            io.BytesIO(pdf_bytes),
            output,
            laparams=LAParams(),
            output_type="text",
            codec="utf-8",
        )
        return output.getvalue()
    except ImportError:
        logger.warning("edpb.pdfminer_not_available; storing raw bytes only")
        return ""
    except Exception as exc:
        logger.warning("edpb.pdf_extraction_failed", error=str(exc))
        return ""


class EdpbSource(Source):
    """Source implementation for EDPB Guidelines and Opinions."""

    source_id = "edpb"
    # 1 req / 2 s
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=60.0,
        )
        # Maps doc_id → PDF URL for use in fetch()
        self._url_cache: dict[str, str] = {}

    async def list_documents(self) -> list[str]:
        """Fetch the document listing and return IDs for Guidelines and Opinions.

        Document IDs are derived from the URL slug, e.g.
        "our-documents/guidelines/guidelines-012023" → "guidelines-012023".
        """
        doc_ids: list[str] = []
        page = 0

        while True:
            url = _LISTING if page == 0 else f"{_LISTING}?page={page}"
            await self._rate_limiter.acquire()
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("edpb.list_fetch_error", url=url, error=str(exc))
                break

            soup = BeautifulSoup(resp.text, "lxml")
            found_on_page = 0

            # Each document appears as a link within a listing item.
            # The type is often indicated in a <span class="...type..."> or in the URL.
            for a_tag in soup.find_all("a", href=True):
                href: str = a_tag["href"]
                lower_href = href.lower()
                # Match Guidelines / Opinions in the URL path
                if not any(t in lower_href for t in ("guideline", "opinion")):
                    continue
                # Build a stable doc_id from the last path segment
                slug = href.rstrip("/").split("/")[-1]
                if not slug or slug in doc_ids:
                    continue

                # Resolve to absolute URL
                abs_href = href if href.startswith("http") else f"{_BASE}{href}"
                self._url_cache[slug] = abs_href
                doc_ids.append(slug)
                found_on_page += 1

            if found_on_page == 0:
                break
            page += 1

        logger.info("edpb.list_done", count=len(doc_ids))
        return doc_ids

    async def _find_pdf_url(self, page_url: str) -> str | None:
        """Given an EDPB document page URL, find the PDF download link."""
        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(page_url)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("edpb.page_fetch_error", url=page_url, error=str(exc))
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if href.lower().endswith(".pdf"):
                return href if href.startswith("http") else f"{_BASE}{href}"
        return None

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the EDPB PDF for the given document ID."""
        page_url = self._url_cache.get(doc_id)
        if not page_url:
            # Best-effort reconstruct URL
            page_url = f"{_LISTING}/{doc_id}"

        pdf_url = await self._find_pdf_url(page_url)
        if not pdf_url:
            # Fallback: the page URL itself might be the PDF
            pdf_url = page_url

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(pdf_url)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("edpb.pdf_fetch_failed", doc_id=doc_id, url=pdf_url, error=str(exc))
            raise

        content_type_header = resp.headers.get("content-type", "")
        is_pdf = "pdf" in content_type_header.lower() or pdf_url.lower().endswith(".pdf")

        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="pdf" if is_pdf else "html",
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Extract text from the EDPB PDF (or HTML fallback)."""
        full_text = ""
        title = ""
        pub_date = datetime.utcnow().date()

        if raw.content_type == "pdf":
            full_text = _extract_pdf_text(raw.raw_bytes)
            # Extract title from first non-empty lines of the PDF text
            lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
            if lines:
                title = lines[0][:255]
        else:
            soup = BeautifulSoup(raw.raw_bytes, "lxml")
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(" ", strip=True)
            time_el = soup.find("time")
            if time_el:
                dt_str = time_el.get("datetime", "") or time_el.get_text(strip=True)
                for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        pub_date = datetime.strptime(dt_str[:10], fmt).date()
                        break
                    except ValueError:
                        continue
            full_text = soup.get_text("\n", strip=True)

        # Determine document type from doc_id
        doc_type_str = raw.source_id.lower()
        doc_type = "guideline" if "guideline" in doc_type_str else "opinion"

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="EU",
            type=doc_type,  # type: ignore[arg-type]
            title=title,
            publication_date=pub_date,
            status="unknown",
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            domain="datos_personales",
        )
