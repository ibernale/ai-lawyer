"""BCRA (Banco Central de la República Argentina) source.

Fetches comunicaciones, circulares and normativa from the BCRA website at
https://www.bcra.gob.ar.
Primary: HTML scraping of https://www.bcra.gob.ar/SistemasFinancieros/sf010000.asp.
Rate limit: 0.33 req/s (conservative — government server).
Domain: regulatorio_bancario_ue_es (international reference — Argentina jurisdiction).
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
_BASE = "https://www.bcra.gob.ar"
_NORMATIVOS_URL = f"{_BASE}/SistemasFinancieros/sf010000.asp"
_DATE_RE = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")
_COMUNIC_RE = re.compile(r"\b(Com\.\s*[A-Z]\s*\d+|Circular\s+\w+\s*\d+)\b", re.IGNORECASE)

_DOC_TYPE_MAP = {
    "comunicacion": "comunicacion",
    "circular": "circular",
    "resolucion": "resolucion",
    "resolución": "resolucion",
    "texto ordenado": "texto_ordenado",
}


def _infer_type(text: str) -> str:
    lower = text.lower()
    for key, val in _DOC_TYPE_MAP.items():
        if key in lower:
            return val
    return "normativo"


class BcraSource(Source):
    """Source implementation for BCRA normativa."""

    source_id = "bcra"
    rate_limit_rps: float = 0.33

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Return BCRA normativo URLs as document IDs (capped at 50)."""
        try:
            await self._rate_limiter.acquire()
            resp = await self._client.get(_NORMATIVOS_URL)
            resp.raise_for_status()
        except Exception:
            logger.exception("bcra.list_failed")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        urls: list[str] = []
        seen: set[str] = set()

        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            if re.search(r"\.(pdf|asp|aspx)$", href, re.IGNORECASE):
                full = href if href.startswith("http") else _BASE + "/" + href.lstrip("/")
                if full not in seen:
                    seen.add(full)
                    urls.append(full)

        logger.info("bcra.list", count=len(urls))
        return urls[:50]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a BCRA document by URL."""
        await self._rate_limiter.acquire()
        resp = await self._client.get(doc_id)
        resp.raise_for_status()
        is_pdf = doc_id.lower().endswith(".pdf")
        content_type = "pdf" if is_pdf else "html"
        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=doc_id,
            content_type=content_type,
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a BCRA page or PDF stub into a CanonicalDocument."""
        if raw.content_type == "pdf":
            return CanonicalDocument(
                source=self.source_id,
                source_id=raw.source_id,
                jurisdiction="AR",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                title=raw.source_id.split("/")[-1],
                type="normativo",
                status="vigente",
                full_text="",
                domain="regulatorio_bancario_ue_es",
                hierarchy=[HierarchyNode(level="organismo", label="BCRA")],
            )

        soup = BeautifulSoup(raw.raw_bytes.decode("utf-8", errors="replace"), "html.parser")

        title = ""
        # BCRA pages often have title in <title> or <h1>
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        elif soup.title:
            title = soup.title.get_text(strip=True)

        # Try to extract comunicación ID from text (e.g. "Com. A 7650")
        full_text_raw = soup.get_text()
        m_com = _COMUNIC_RE.search(full_text_raw)
        if m_com and not title:
            title = m_com.group(0)

        pub_date: date = date.today()
        m = _DATE_RE.search(full_text_raw)
        if m:
            try:
                pub_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        doc_type = _infer_type(title or raw.source_id)
        full_text = soup.get_text(separator="\n", strip=True)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="AR",
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            title=title,
            type=doc_type,
            publication_date=pub_date,
            status="vigente",
            full_text=full_text,
            domain="regulatorio_bancario_ue_es",
            hierarchy=[HierarchyNode(level="organismo", label="BCRA")],
        )
