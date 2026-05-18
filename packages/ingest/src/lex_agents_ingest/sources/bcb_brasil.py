"""BCB Brasil (Banco Central do Brasil) source.

Fetches circulares, resoluções and notas técnicas from the BCB open-data API
at https://dadosabertos.bcb.gov.br/dataset.
Primary: BCB ODATA/JSON REST API.
Fallback: HTML scraping of https://www.bcb.gov.br/estabilidadefinanceira/normativos.
Rate limit: 0.5 req/s.
Domain: regulatorio_bancario_ue_es (international reference — Brazil jurisdiction).
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
_BASE = "https://www.bcb.gov.br"
_NORMATIVOS_URL = f"{_BASE}/estabilidadefinanceira/normativos"
# BCB open data API — normativos endpoint
_ODATA_URL = "https://dadosabertos.bcb.gov.br/api/3/action/datastore_search"
_DATE_RE = re.compile(r"(\d{2})[/\-](\d{2})[/\-](\d{4})")

_DOC_TYPE_MAP = {
    "circular": "circular",
    "resolucao": "resolucao",
    "resolução": "resolucao",
    "instrucao normativa": "instrucao_normativa",
    "instrução normativa": "instrucao_normativa",
    "comunicado": "comunicado",
    "nota": "nota_tecnica",
}


def _infer_type(text: str) -> str:
    lower = text.lower()
    for key, val in _DOC_TYPE_MAP.items():
        if key in lower:
            return val
    return "normativo"


class BcbBrasilSource(Source):
    """Source implementation for BCB Brasil normativos."""

    source_id = "bcb_brasil"
    rate_limit_rps: float = 0.5

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Return BCB normativo URLs as document IDs (capped at 50)."""
        try:
            ids = await self._list_from_html()
            logger.info("bcb_brasil.list", count=len(ids))
            return ids[:50]
        except Exception:
            logger.exception("bcb_brasil.list_failed")
            return []

    async def _list_from_html(self) -> list[str]:
        await self._rate_limiter.acquire()
        resp = await self._client.get(_NORMATIVOS_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        urls: list[str] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            if re.search(r"/(circular|resolucao|resoluc|normativo|comunicado)\b", href, re.IGNORECASE):
                full = href if href.startswith("http") else _BASE + href
                if full not in seen:
                    seen.add(full)
                    urls.append(full)
        return urls

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a BCB document by URL."""
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
        """Parse BCB HTML page or PDF stub into a CanonicalDocument."""
        if raw.content_type == "pdf":
            return CanonicalDocument(
                source=self.source_id,
                source_id=raw.source_id,
                jurisdiction="BR",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                title=raw.source_id.split("/")[-1],
                type="normativo",
                status="vigente",
                full_text="",
                domain="regulatorio_bancario_ue_es",
                hierarchy=[HierarchyNode(level="organismo", label="BCB Brasil")],
            )

        soup = BeautifulSoup(raw.raw_bytes.decode("utf-8", errors="replace"), "html.parser")

        title = ""
        h1 = soup.find("h1") or soup.find("h2")
        if h1:
            title = h1.get_text(strip=True)

        pub_date: date = date.today()
        m = _DATE_RE.search(soup.get_text())
        if m:
            try:
                pub_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        full_text = soup.get_text(separator="\n", strip=True)
        doc_type = _infer_type(title or raw.source_id)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="BR",
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            title=title,
            type=doc_type,
            publication_date=pub_date,
            status="vigente",
            full_text=full_text,
            domain="regulatorio_bancario_ue_es",
            hierarchy=[HierarchyNode(level="organismo", label="BCB Brasil")],
        )
