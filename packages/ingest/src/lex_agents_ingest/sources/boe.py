"""BOE (Boletín Oficial del Estado) legal document source implementation."""

from __future__ import annotations

from datetime import date, datetime

import httpx
import structlog
from lxml import etree

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_RANGO_MAP: dict[str, str] = {
    "Ley": "ley",
    "Real Decreto": "real_decreto",
    "Real Decreto-ley": "real_decreto",
}


class BoeSource(Source):
    """Source implementation for the BOE XML API."""

    source_id = "boe"
    rate_limit_rps: float = 0.5

    BASE_URL = "https://boe.es/diario_boe/xml.php?id={doc_id}"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient()

    async def list_documents(self) -> list[str]:
        """Return hardcoded sample BOE document IDs."""
        return ["BOE-A-2014-6732", "BOE-A-2015-1510", "BOE-A-2019-3814"]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a BOE document by ID and return it as a RawDocument."""
        url = self.BASE_URL.format(doc_id=doc_id)
        response = await self._client.get(url)
        response.raise_for_status()
        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=url,
            content_type="xml",
            raw_bytes=response.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a BOE XML RawDocument into a CanonicalDocument."""
        try:
            root = etree.fromstring(raw.raw_bytes)
        except etree.XMLSyntaxError:
            logger.warning("boe.xml_parse_failed", source_id=raw.source_id)
            return CanonicalDocument(
                source="boe",
                source_id=raw.source_id,
                jurisdiction="ES",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                full_text=raw.raw_bytes.decode("utf-8", errors="replace"),
                status="unknown",
            )

        meta = root.find("metadatos")

        title = ""
        pub_date: date = date.today()
        doc_type: str = "other"

        if meta is not None:
            titulo_el = meta.find("titulo")
            if titulo_el is not None and titulo_el.text:
                title = titulo_el.text.strip()

            fecha_el = meta.find("fecha_publicacion")
            if fecha_el is not None and fecha_el.text:
                raw_date = fecha_el.text.strip()
                for fmt in ("%Y%m%d", "%d/%m/%Y"):
                    try:
                        pub_date = datetime.strptime(raw_date, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    logger.warning(
                        "boe.date_parse_failed",
                        source_id=raw.source_id,
                        raw_date=raw_date,
                    )

            rango_el = meta.find("rango")
            if rango_el is not None and rango_el.text:
                doc_type = _RANGO_MAP.get(rango_el.text.strip(), "other")

        hierarchy: list[HierarchyNode] = []
        texts: list[str] = []

        texto_el = root.find("texto")
        if texto_el is not None:
            # Try nested <articulo> structure first (older BOE format)
            articulos = texto_el.findall("articulo")
            if articulos:
                for articulo in articulos:
                    num = articulo.get("num", "")
                    marginales_el = articulo.find("marginales")
                    art_title = (
                        marginales_el.text.strip()
                        if marginales_el is not None and marginales_el.text
                        else ""
                    )
                    hierarchy.append(
                        HierarchyNode(level="articulo", number=num, title=art_title)
                    )
                    parts: list[str] = []
                    for parrafo in articulo.findall("parrafo"):
                        if parrafo.text:
                            parts.append(parrafo.text.strip())
                    if parts:
                        texts.append("\n".join(parts))
            else:
                # Modern BOE format: flat <p class="..."> elements
                art_buf: list[str] = []
                for p_el in texto_el.iter("p"):
                    css_class = p_el.get("class", "")
                    # Collect all text content; normalize non-breaking spaces
                    raw_text = "".join(p_el.itertext()).replace("\xa0", " ").strip()
                    if not raw_text:
                        continue
                    if css_class in ("articulo", "titulo_articulo"):
                        # Flush previous article buffer
                        if art_buf:
                            texts.append("\n".join(art_buf))
                            art_buf = []
                        hierarchy.append(
                            HierarchyNode(level="articulo", number="", title=raw_text)
                        )
                        art_buf.append(raw_text)
                    else:
                        art_buf.append(raw_text)
                if art_buf:
                    texts.append("\n".join(art_buf))

        full_text = "\n\n".join(texts)

        return CanonicalDocument(
            source="boe",
            source_id=raw.source_id,
            jurisdiction="ES",
            type=doc_type,  # type: ignore[arg-type]
            title=title,
            publication_date=pub_date,
            status="vigente",
            hierarchy=hierarchy,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
        )
