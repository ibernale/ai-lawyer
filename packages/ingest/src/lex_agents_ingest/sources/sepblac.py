"""SEPBLAC (Servicio Ejecutivo de la Comisión de Prevención del Blanqueo de Capitales) source.

Fetches circulares, guías y memorias anuales published at https://www.sepblac.es.
Primary: HTML scraping of the publications listing.
Rate limit: 0.33 req/s (conservative — government server).
Domain: aml_compliance.
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
_BASE = "https://www.sepblac.es"
_LISTINGS = [
    f"{_BASE}/es/sujetos-obligados/guias-y-comunicados",
    f"{_BASE}/es/publicaciones",
]
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_DATE_RE = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")

_DOC_TYPE_MAP = {
    "guia": "guia",
    "circular": "circular",
    "memoria": "memoria",
    "informe": "informe",
    "comunicado": "comunicado",
    "instruccion": "instruccion",
}


def _infer_type(text: str) -> str:
    lower = text.lower()
    for key, val in _DOC_TYPE_MAP.items():
        if key in lower:
            return val
    return "documento"


class SepblacSource(Source):
    """Source implementation for SEPBLAC publications."""

    source_id = "sepblac"
    rate_limit_rps: float = 0.33

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Return absolute URLs of SEPBLAC publications as document IDs."""
        doc_urls: list[str] = []
        for listing_url in _LISTINGS:
            try:
                await self._rate_limiter.acquire()
                resp = await self._client.get(listing_url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    href: str = link["href"]
                    # Filter links that point to PDF or detail pages
                    if href.endswith(".pdf") or "/es/sujetos-obligados/" in href or "/es/publicaciones/" in href:
                        full = href if href.startswith("http") else _BASE + href
                        doc_urls.append(full)
            except Exception:
                logger.exception("sepblac.list_failed", url=listing_url)

        # Deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for url in doc_urls:
            if url not in seen:
                seen.add(url)
                result.append(url)
        logger.info("sepblac.list", count=len(result))
        return result[:50]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a SEPBLAC document by URL (doc_id = absolute URL)."""
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
        """Parse a SEPBLAC HTML page or PDF stub into a CanonicalDocument."""
        if raw.content_type == "pdf":
            # PDF: return stub — text extraction handled by Docling extractor
            return CanonicalDocument(
                source=self.source_id,
                source_id=raw.source_id,
                jurisdiction="ES",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                title=raw.source_id.split("/")[-1].replace("-", " ").replace("_", " "),
                type="documento",
                status="vigente",
                full_text="",  # populated by document extraction pipeline
                domain="aml_compliance",
                hierarchy=[HierarchyNode(level="organismo", label="SEPBLAC")],
            )

        soup = BeautifulSoup(raw.raw_bytes.decode("utf-8", errors="replace"), "html.parser")

        # Title
        title = ""
        for selector in ("h1", "h2"):
            el = soup.find(selector)
            if el:
                title = el.get_text(strip=True)
                break

        # Date
        pub_date: date = date.today()
        text_content = soup.get_text()
        m = _DATE_RE.search(text_content)
        if m:
            try:
                pub_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
        else:
            # Fallback: extract year from URL or text
            ym = _YEAR_RE.search(raw.source_id)
            if ym:
                try:
                    pub_date = date(int(ym.group(1)), 1, 1)
                except ValueError:
                    pass

        full_text = soup.get_text(separator="\n", strip=True)
        doc_type = _infer_type(title or raw.source_id)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="ES",
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            title=title,
            type=doc_type,
            publication_date=pub_date,
            status="vigente",
            full_text=full_text,
            domain="aml_compliance",
            hierarchy=[HierarchyNode(level="organismo", label="SEPBLAC")],
        )
