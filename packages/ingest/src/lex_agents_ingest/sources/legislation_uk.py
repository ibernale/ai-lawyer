"""legislation.gov.uk REST API source.

Uses the official XML API:
  https://www.legislation.gov.uk/{type}/{year}/{number}/data.xml

Initial coverage:
  - FSMA 2000        (ukpga/2000/8)
  - Bank of England Act 1998  (ukpga/1998/11)

Further items can be added to INITIAL_CORPUS below.

Rate limit: 1 req / 1 s.
Domain: regulatorio_bancario.
Jurisdiction: GB.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import structlog
from lxml import etree

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_BASE = "https://www.legislation.gov.uk"
_XML_TEMPLATE = f"{_BASE}/{{path}}/data.xml"

# Each entry is (doc_id, legislation_path)
INITIAL_CORPUS: list[tuple[str, str]] = [
    ("FSMA-2000", "ukpga/2000/8"),
    ("BOE-ACT-1998", "ukpga/1998/11"),
]

# XML namespaces used by legislation.gov.uk (AKN / leg / dc)
_NS = {
    "leg": "http://www.legislation.gov.uk/namespaces/legislation",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dct": "http://purl.org/dc/terms/",
    "akn": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0",
}


def _text(el: etree._Element | None) -> str:
    """Return stripped itertext of an element, or empty string."""
    if el is None:
        return ""
    return " ".join(el.itertext()).strip()


class LegislationUkSource(Source):
    """Source implementation for legislation.gov.uk XML API."""

    source_id = "legislation_uk"
    # 1 req / 1 s
    rate_limit_rps: float = 1.0

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )
        self._path_map: dict[str, str] = dict(INITIAL_CORPUS)

    async def list_documents(self) -> list[str]:
        """Return the initial corpus of UK legislation IDs."""
        return list(self._path_map.keys())

    async def fetch(self, doc_id: str) -> RawDocument:
        """Download the XML for the given legislation ID."""
        path = self._path_map.get(doc_id)
        if not path:
            raise ValueError(f"Unknown UK legislation doc_id: {doc_id!r}")

        url = _XML_TEMPLATE.format(path=path)
        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(
                url,
                headers={"Accept": "application/xml, text/xml;q=0.9"},
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("legislation_uk.fetch_failed", doc_id=doc_id, url=url, error=str(exc))
            raise

        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="xml",
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse legislation.gov.uk XML into a CanonicalDocument."""
        try:
            root = etree.fromstring(raw.raw_bytes)
        except etree.XMLSyntaxError as exc:
            logger.warning("legislation_uk.xml_parse_failed", source_id=raw.source_id, error=str(exc))
            return CanonicalDocument(
                source=self.source_id,
                source_id=raw.source_id,
                jurisdiction="GB",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                full_text=raw.raw_bytes.decode("utf-8", errors="replace"),
                status="unknown",
                domain="regulatorio_bancario",
            )

        # Strip namespace for simpler XPath where needed
        def _find(xp: str) -> etree._Element | None:
            # Try with and without namespace prefixes
            for ns_map in (_NS, {}):
                try:
                    el = root.find(xp, ns_map)
                    if el is not None:
                        return el
                except Exception:
                    pass
            return None

        def _find_by_localname(tag: str) -> etree._Element | None:
            """Find first element matching local tag name anywhere in tree."""
            for el in root.iter():
                local = etree.QName(el.tag).localname if el.tag and not isinstance(el.tag, str) else (
                    el.tag.split("}")[-1] if "}" in el.tag else el.tag
                )
                if local == tag:
                    return el
            return None

        # --- Title ---
        title = ""
        for tag in ("Title", "title", "LongTitle", "dc:title"):
            el = _find(f".//{tag}") or _find_by_localname(tag.split(":")[-1])
            if el is not None:
                title = _text(el)
                break

        # --- Date ---
        pub_date = datetime.utcnow().date()
        for tag in ("dct:valid", "dc:date", "Date", "Year"):
            el = _find(f".//{tag}") or _find_by_localname(tag.split(":")[-1])
            if el is not None and el.text:
                for fmt in ("%Y-%m-%d", "%Y"):
                    try:
                        pub_date = datetime.strptime(el.text.strip()[:10], fmt).date()
                        break
                    except ValueError:
                        continue
                break

        # --- Hierarchy & full text ---
        hierarchy: list[HierarchyNode] = []
        texts: list[str] = []

        # Parts → Chapters → Sections
        for part in root.iter():
            local_tag = (
                etree.QName(part.tag).localname
                if part.tag and not isinstance(part.tag, str)
                else (part.tag.split("}")[-1] if "}" in part.tag else part.tag)
            )
            if local_tag == "Part":
                num = part.get("Number", part.get("number", ""))
                heading_el = None
                for child in part:
                    child_local = (
                        etree.QName(child.tag).localname
                        if child.tag and not isinstance(child.tag, str)
                        else (child.tag.split("}")[-1] if "}" in child.tag else child.tag)
                    )
                    if child_local in ("Heading", "Title"):
                        heading_el = child
                        break
                hierarchy.append(
                    HierarchyNode(
                        level="titulo",
                        number=num,
                        title=_text(heading_el),
                    )
                )
            elif local_tag in ("Section", "Article"):
                num = part.get("IdURI", part.get("id", "")).split("/")[-1]
                heading_el = None
                for child in part:
                    child_local = (
                        etree.QName(child.tag).localname
                        if child.tag and not isinstance(child.tag, str)
                        else (child.tag.split("}")[-1] if "}" in child.tag else child.tag)
                    )
                    if child_local in ("Heading", "Title"):
                        heading_el = child
                        break
                art_text = _text(part)
                hierarchy.append(
                    HierarchyNode(level="articulo", number=num, title=_text(heading_el))
                )
                if art_text:
                    texts.append(art_text)

        full_text = "\n\n".join(texts) if texts else _text(root)

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="GB",
            type="ley",  # type: ignore[arg-type]
            title=title,
            publication_date=pub_date,
            status="vigente",
            hierarchy=hierarchy,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            domain="regulatorio_bancario",
        )
