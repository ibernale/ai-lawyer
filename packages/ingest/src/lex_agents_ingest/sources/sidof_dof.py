"""SIDOF DOF (Diario Oficial de la Federación — Mexico) source. ADR 0025."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalBulletin, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

SIDOF_BASE = "https://sidof.segob.gob.mx/"

RELEVANT_AUTHORITIES = {
    "CNBV",
    "Banxico",
    "SHCP",
    "CONDUSEF",
    "Banco de México",
}

_DOC_TYPE_RE = re.compile(
    r"\b(NOM|NMX|DECRETO|ACUERDO|RESOLUCIÓN|CIRCULAR)\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\b")
_VIGENCIA_RE = re.compile(
    r"(?:entrar[áa]\s+en\s+vigor|entrada\s+en\s+vigor)[^\d]*(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_date_es(day: str, month_name: str, year: str) -> date | None:
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


class SidofDOFSource(Source):
    """Source for the Mexican Diario Oficial de la Federación via SIDOF.

    In fixture mode (*fixture_path* set) reads local HTML files.
    In real mode uses the SIDOF public web service (no auth required).
    """

    source_id = "sidof_dof"
    rate_limit_rps: float = 0.5

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__()
        self._fixture_path = fixture_path

    # ------------------------------------------------------------------
    # list_documents
    # ------------------------------------------------------------------

    async def list_documents(self, for_date: date | None = None) -> list[str]:  # type: ignore[override]
        """Return relevant DOF note IDs for *for_date* (default today)."""
        if self._fixture_path is not None:
            return [p.stem for p in sorted(self._fixture_path.glob("*.html"))]

        target = for_date or datetime.now(tz=timezone.utc).date()

        import httpx

        url = f"{SIDOF_BASE}WS_getDiarioFecha"
        params = {
            "year": str(target.year),
            "month": str(target.month).zfill(2),
        }

        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.content, "lxml")
        doc_ids: list[str] = []
        for item in soup.find_all(["nota", "item", "li"]):
            text = item.get_text(" ", strip=True)
            if any(auth in text for auth in RELEVANT_AUTHORITIES):
                # Extract an ID from an id attribute or href
                item_id = item.get("id") or item.get("nota_id")
                if not item_id:
                    a_tag = item.find("a", href=True)
                    if a_tag:
                        item_id = a_tag["href"].rstrip("/").split("/")[-1]
                if item_id:
                    doc_ids.append(str(item_id))
        return doc_ids

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    async def fetch(self, doc_id: str) -> RawDocument:
        """Return HTML content for *doc_id*."""
        if self._fixture_path is not None:
            fixture_file = self._fixture_path / f"{doc_id}.html"
            raw_bytes = fixture_file.read_bytes()
            return RawDocument(
                source="sidof_dof",
                source_id=doc_id,
                raw_url=f"file://{fixture_file}",
                content_type="html",
                raw_bytes=raw_bytes,
                fetched_at=datetime.now(tz=timezone.utc),
            )

        import httpx

        url = f"{SIDOF_BASE}notas/{doc_id}"
        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        return RawDocument(
            source="sidof_dof",
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="html",
            raw_bytes=resp.content,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    # ------------------------------------------------------------------
    # parse_to_canonical
    # ------------------------------------------------------------------

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalBulletin:  # type: ignore[override]
        """Parse a DOF HTML note into a CanonicalBulletin."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw.raw_bytes, "lxml")
        full_text = soup.get_text("\n", strip=True)

        # --- Issuing authority ---
        issuing_authority = ""
        for auth in RELEVANT_AUTHORITIES:
            if auth in full_text:
                issuing_authority = auth
                break

        # --- Document type ---
        doc_type = "other"
        dt_match = _DOC_TYPE_RE.search(full_text[:500])
        if dt_match:
            raw_type = dt_match.group(1).upper()
            _type_map = {
                "NOM": "nom",
                "NMX": "nmx",
                "DECRETO": "decreto",
                "ACUERDO": "acuerdo",
                "RESOLUCIÓN": "resolución",
                "CIRCULAR": "circular",
            }
            doc_type = _type_map.get(raw_type, "other")

        # --- Publication date ---
        pub_date = raw.fetched_at.date()
        date_match = _DATE_RE.search(full_text[:500])
        if date_match:
            parsed = _parse_date_es(*date_match.groups())
            if parsed:
                pub_date = parsed

        # --- Entry into force ---
        entry_into_force: date | None = None
        vigencia_match = _VIGENCIA_RE.search(full_text)
        if vigencia_match:
            parsed_vigencia = _parse_date_es(*vigencia_match.groups())
            if parsed_vigencia:
                entry_into_force = parsed_vigencia

        # --- Title ---
        title_tag = soup.find(["h1", "h2", "h3"])
        title = title_tag.get_text(" ", strip=True) if title_tag else raw.source_id

        return CanonicalBulletin(
            source="sidof_dof",
            source_id=raw.source_id,
            jurisdiction="MX",
            type=doc_type,  # type: ignore[arg-type]
            title=title,
            publication_date=pub_date,
            entry_into_force=entry_into_force,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            bulletin="DOF",
            issuing_authority=issuing_authority,
            document_type=doc_type,
            extra={"language": "es-MX"},
        )
