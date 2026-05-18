"""Federal Register (US) source.

Fetches final rules and proposed rules relevant to banking/financial regulation
from the Federal Register JSON API at https://www.federalregister.gov/api/v1/.
Rate limit: 1 req/s (API allows up to 1000 req/day without key).
Domain: regulatorio_bancario_ue_es (international reference), aml_compliance.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx
import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, HierarchyNode, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_UA = "lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)"
_API_BASE = "https://www.federalregister.gov/api/v1"

# Agencies relevant to financial regulation: OCC, Fed, FDIC, FinCEN, CFPB, SEC, CFTC, OFAC
_RELEVANT_AGENCIES = ["federal-reserve-system", "comptroller-of-the-currency", "financial-crimes-enforcement-network", "consumer-financial-protection-bureau"]

_DOCUMENT_TYPES = ["RULE", "PRORULE"]  # Final rules + proposed rules only

_DOMAIN_MAP = {
    "financial-crimes-enforcement-network": "aml_compliance",
}


class FederalRegisterSource(Source):
    """Source implementation for US Federal Register rules."""

    source_id = "federal_register"
    rate_limit_rps: float = 1.0

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client if http_client is not None else httpx.AsyncClient(
            headers={"User-Agent": _UA},
            follow_redirects=True,
            timeout=30.0,
        )

    async def list_documents(self) -> list[str]:
        """Return Federal Register document numbers (e.g. '2024-12345').

        Queries the Federal Register API for recent rules from relevant agencies.
        Returns up to 50 document numbers.
        """
        doc_numbers: list[str] = []
        seen: set[str] = set()

        for agency in _RELEVANT_AGENCIES:
            try:
                await self._rate_limiter.acquire()
                resp = await self._client.get(
                    f"{_API_BASE}/documents.json",
                    params={
                        "conditions[agencies][]": agency,
                        "conditions[type][]": _DOCUMENT_TYPES,
                        "per_page": 10,
                        "order": "newest",
                        "fields[]": ["document_number", "title", "publication_date", "type"],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("results", []):
                    num = item.get("document_number", "")
                    if num and num not in seen:
                        seen.add(num)
                        doc_numbers.append(num)
                if len(doc_numbers) >= 50:
                    break
            except Exception:
                logger.exception("federal_register.list_failed", agency=agency)

        logger.info("federal_register.list", count=len(doc_numbers))
        return doc_numbers[:50]

    async def fetch(self, doc_id: str) -> RawDocument:
        """Fetch a Federal Register document by document number."""
        await self._rate_limiter.acquire()
        resp = await self._client.get(
            f"{_API_BASE}/documents/{doc_id}.json",
            params={"fields[]": ["document_number", "title", "abstract", "full_text_xml_url",
                                  "publication_date", "type", "agencies", "action", "html_url"]},
        )
        resp.raise_for_status()
        return RawDocument(
            source=self.source_id,
            source_id=doc_id,
            raw_url=f"https://www.federalregister.gov/documents/{doc_id}",
            content_type="json",
            raw_bytes=resp.content,
            fetched_at=datetime.utcnow(),
        )

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse a Federal Register JSON response into a CanonicalDocument."""
        import json

        try:
            data = json.loads(raw.raw_bytes)
        except Exception:
            logger.warning("federal_register.json_parse_failed", source_id=raw.source_id)
            return CanonicalDocument(
                source=self.source_id,
                source_id=raw.source_id,
                jurisdiction="US",
                raw_url=raw.raw_url,
                fetched_at=raw.fetched_at,
                title=raw.source_id,
                type="rule",
                status="unknown",
                full_text="",
                domain="regulatorio_bancario_ue_es",
            )

        title = data.get("title", "")
        abstract = data.get("abstract", "") or ""

        pub_date: date = date.today()
        pub_date_str = data.get("publication_date", "")
        if pub_date_str:
            try:
                pub_date = date.fromisoformat(pub_date_str)
            except ValueError:
                pass

        doc_type = data.get("type", "RULE").lower()
        if doc_type == "prorule":
            doc_type = "proposed_rule"
            status = "propuesta"
        else:
            doc_type = "rule"
            status = "vigente"

        # Determine domain from agency slugs
        agencies = data.get("agencies", [])
        agency_slugs = [a.get("slug", "") if isinstance(a, dict) else str(a) for a in agencies]
        domain = "regulatorio_bancario_ue_es"
        for slug in agency_slugs:
            if slug in _DOMAIN_MAP:
                domain = _DOMAIN_MAP[slug]
                break

        # Full text: prefer abstract since full XML would require an extra fetch
        full_text = f"{title}\n\n{abstract}"

        agency_names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in agencies]

        return CanonicalDocument(
            source=self.source_id,
            source_id=raw.source_id,
            jurisdiction="US",
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            title=title,
            type=doc_type,
            publication_date=pub_date,
            status=status,
            full_text=full_text,
            domain=domain,
            hierarchy=[
                HierarchyNode(level="organismo", label=", ".join(agency_names) or "Federal Register"),
            ],
        )
