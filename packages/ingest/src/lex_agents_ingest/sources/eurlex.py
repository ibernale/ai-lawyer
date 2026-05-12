"""EUR-Lex (CELLAR/SPARQL) legal document source implementation."""

from __future__ import annotations

from datetime import date, datetime

import httpx
import structlog
from lxml import etree

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_CELEX_TYPE_MAP: dict[str, str] = {
    "R": "regulation",
    "L": "directive",
    "D": "other",
}

_SPARQL_QUERY_TEMPLATE = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?work WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(?celex = "{celex_id}")
}}
"""

_FALLBACK_URL = (
    "https://eur-lex.europa.eu/legal-content/ES/TXT/XML/?uri=CELEX:{doc_id}"
)


class EurlexSource(Source):
    """Source implementation for EUR-Lex documents via CELLAR/SPARQL."""

    source_id = "eurlex"
    rate_limit_rps: float = 0.5

    CELLAR_BASE = "https://publications.europa.eu/resource/cellar/{cellar_id}"
    SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient()

    async def list_documents(self) -> list[str]:
        """Return hardcoded sample EUR-Lex CELEX document IDs."""
        return [
            "32013R0575",  # CRR — expected by golden dataset BANK-EU-001
            "32013L0036",
            "32013R1024",
            "32019R0876",  # CRR II — expected by golden dataset BANK-EU-013
            "32019R2033",
            "32019L2034",
            "32024R1623",  # CRR III — expected by golden dataset BANK-EU-021
        ]

    async def _resolve_via_sparql(self, doc_id: str) -> str | None:
        """Resolve a CELEX ID to a Cellar URI via SPARQL; return None on failure."""
        query = _SPARQL_QUERY_TEMPLATE.format(celex_id=doc_id)
        try:
            response = await self._client.post(
                self.SPARQL_ENDPOINT,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
            )
            response.raise_for_status()
            data = response.json()
            bindings = data.get("results", {}).get("bindings", [])
            if bindings:
                return bindings[0]["work"]["value"]
        except Exception as exc:
            logger.warning("eurlex.sparql_failed", doc_id=doc_id, error=str(exc))
        return None

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch an EUR-Lex document by CELEX ID and return it as a RawDocument."""
        cellar_uri = await self._resolve_via_sparql(doc_id)

        raw_bytes: bytes | None = None
        used_url: str = ""

        if cellar_uri:
            try:
                response = await self._client.get(
                    cellar_uri,
                    headers={
                        "Accept": "application/xml, application/xhtml+xml;q=0.9"
                    },
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "pdf" in content_type.lower():
                    logger.warning(
                        "eurlex.pdf_not_supported", doc_id=doc_id, uri=cellar_uri
                    )
                    raise ValueError("PDF not supported in Fase 2")
                raw_bytes = response.content
                used_url = cellar_uri
            except ValueError:
                raise
            except Exception as exc:
                logger.warning(
                    "eurlex.cellar_fetch_failed",
                    doc_id=doc_id,
                    uri=cellar_uri,
                    error=str(exc),
                )

        if raw_bytes is None:
            fallback_url = _FALLBACK_URL.format(doc_id=doc_id)
            logger.warning("eurlex.using_fallback_url", doc_id=doc_id)
            response = await self._client.get(fallback_url)
            response.raise_for_status()
            raw_bytes = response.content
            used_url = fallback_url

        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=used_url,
            content_type="xml",
            raw_bytes=raw_bytes,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse an EUR-Lex XML RawDocument into a CanonicalDocument."""
        try:
            root = etree.fromstring(raw.raw_bytes)
        except etree.XMLSyntaxError:
            logger.warning("eurlex.xml_parse_failed", source_id=raw.source_id)
            return CanonicalDocument(
                source="eurlex",
                source_id=raw.source_id,
                jurisdiction="EU",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                full_text=raw.raw_bytes.decode("utf-8", errors="replace"),
                status="unknown",
            )

        # --- Title ---
        title = ""
        for tag in ("TITLE/TI", "doc.title", "TI"):
            el = root.find(tag)
            if el is not None and el.text:
                title = el.text.strip()
                break

        # --- Date ---
        pub_date: date = date.today()
        for tag in ("DATE.PUB", "date"):
            el = root.find(tag)
            if el is not None and el.text:
                raw_date = el.text.strip()
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y"):
                    try:
                        pub_date = datetime.strptime(raw_date, fmt).date()
                        break
                    except ValueError:
                        continue
                break
            # also try attribute
            date_attr = root.get("DATE")
            if date_attr:
                try:
                    pub_date = datetime.strptime(date_attr, "%Y-%m-%d").date()
                except ValueError:
                    pass
                break

        # --- Document type from CELEX prefix ---
        doc_type: str = "other"
        # CELEX format: 32013R0575 — sector(1) + year(4) + type(1) + number(4)
        # type letter is at index 5
        if len(raw.source_id) >= 6:
            type_char = raw.source_id[5]
            doc_type = _CELEX_TYPE_MAP.get(type_char, "other")

        # --- Hierarchy & full_text ---
        hierarchy: list[HierarchyNode] = []
        texts: list[str] = []

        # Considerandos / recitals
        for recital in root.iter("RECITAL"):
            num = recital.get("NUM", "")
            recital_text = "".join(recital.itertext()).strip()
            hierarchy.append(
                HierarchyNode(level="considerando", number=num, title="")
            )
            if recital_text:
                texts.append(recital_text)

        # WHEREAS elements
        for whereas in root.iter("WHEREAS"):
            whereas_text = "".join(whereas.itertext()).strip()
            hierarchy.append(
                HierarchyNode(level="considerando", number="", title="")
            )
            if whereas_text:
                texts.append(whereas_text)

        # Articles
        for article in root.iter("ARTICLE"):
            identifier = article.get("IDENTIFIER", "")
            ti_art = article.find("TI.ART")
            art_title = (
                ti_art.text.strip()
                if ti_art is not None and ti_art.text
                else ""
            )
            hierarchy.append(
                HierarchyNode(level="articulo", number=identifier, title=art_title)
            )
            parts: list[str] = []
            for parag in article.findall("PARAG"):
                parag_text = "".join(parag.itertext()).strip()
                if parag_text:
                    parts.append(parag_text)
            if parts:
                texts.append("\n".join(parts))

        full_text = "\n\n".join(texts)

        return CanonicalDocument(
            source="eurlex",
            source_id=raw.source_id,
            jurisdiction="EU",
            type=doc_type,  # type: ignore[arg-type]
            title=title,
            publication_date=pub_date,
            status="unknown",
            hierarchy=hierarchy,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
        )
