"""Tribunal Constitucional (TC) source. ADR 0025.

Reference: docs/decisions/0025-cendoj-dev-mode.md
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalCaseLaw, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_ECLI_RE = re.compile(r"ECLI:ES:TC:\d{4}:\d+")
_TC_NUM_RE = re.compile(r"\b(\d+)/(\d{4})\b")


class TribunalConstitucionalSource(Source):
    """Tribunal Constitucional source with fixture support.

    More permissive than CENDOJ (1 req/s). No QuotaTracker needed.
    In fixture mode (*fixture_path* set) no HTTP calls are made.
    """

    source_id = "tribunal_constitucional"
    rate_limit_rps: float = 1.0

    BASE_URL = "https://hj.tribunalconstitucional.es/"

    def __init__(self, fixture_path: Path | None = None) -> None:
        super().__init__()
        self._fixture_path = fixture_path

    # ------------------------------------------------------------------
    # list_documents
    # ------------------------------------------------------------------

    async def list_documents(self, filters: dict | None = None) -> list[str]:  # type: ignore[override]
        """Return document IDs — fixture filenames or live search results."""
        if self._fixture_path is not None:
            return [p.stem for p in sorted(self._fixture_path.glob("*.html"))]

        import httpx

        params: dict[str, str] = {}
        if filters:
            params.update({k: str(v) for k, v in filters.items()})

        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.content, "lxml")
        doc_ids: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if "sentencia" in href.lower() or "stc" in href.lower():
                slug = href.rstrip("/").split("/")[-1]
                if slug:
                    doc_ids.append(slug)
        return doc_ids

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    async def fetch(self, doc_id: str) -> RawDocument:
        """Return a RawDocument for *doc_id*."""
        if self._fixture_path is not None:
            fixture_file = self._fixture_path / f"{doc_id}.html"
            raw_bytes = fixture_file.read_bytes()
            return RawDocument(
                source="tribunal_constitucional",
                source_id=doc_id,
                raw_url=f"file://{fixture_file}",
                content_type="html",
                raw_bytes=raw_bytes,
                fetched_at=datetime.now(tz=timezone.utc),
            )

        import httpx

        url = f"{self.BASE_URL}es/jurisprudencia/{doc_id}"
        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        return RawDocument(
            source="tribunal_constitucional",
            source_id=doc_id,
            raw_url=str(resp.url),
            content_type="html",
            raw_bytes=resp.content,
            fetched_at=datetime.now(tz=timezone.utc),
        )

    # ------------------------------------------------------------------
    # parse_to_canonical
    # ------------------------------------------------------------------

    def parse_to_canonical(self, raw: RawDocument) -> CanonicalCaseLaw:  # type: ignore[override]
        """Parse a TC HTML document into a CanonicalCaseLaw."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw.raw_bytes, "lxml")
        full_text = soup.get_text("\n", strip=True)

        # --- Document type ---
        doc_type: str = "sentencia"
        title_lower = full_text[:500].lower()
        if "auto" in title_lower:
            doc_type = "auto"
        elif "providencia" in title_lower:
            doc_type = "providencia"

        # --- Number and year ---
        number = ""
        year = ""
        num_match = _TC_NUM_RE.search(raw.source_id)
        if num_match:
            number = num_match.group(1)
            year = num_match.group(2)
        else:
            # Try from full text
            num_match_text = _TC_NUM_RE.search(full_text[:500])
            if num_match_text:
                number = num_match_text.group(1)
                year = num_match_text.group(2)

        # --- ECLI ---
        ecli_match = _ECLI_RE.search(full_text)
        if ecli_match:
            ecli = ecli_match.group(0)
        else:
            ecli = f"ECLI:ES:TC:{year}:{number}" if number and year else None

        # --- Sala ---
        chamber = None
        sala_match = re.search(
            r"(Pleno|Sala\s+(?:Primera|Segunda))",
            full_text[:1000],
            re.IGNORECASE,
        )
        if sala_match:
            chamber = sala_match.group(1)

        # --- Magistrado ponente ---
        judges: list[str] = []
        ponente_match = re.search(
            r"(?:Magistrado\s+[Pp]onente|Ponente)[:\s]+([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s,\.]+)",
            full_text,
        )
        if ponente_match:
            judges = [ponente_match.group(1).strip()[:80]]

        # --- Decision date ---
        decision_date: date = raw.fetched_at.date()
        date_match = re.search(r"\b(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\b", full_text)
        if date_match:
            _months = {
                "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
                "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
                "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
            }
            day_str, month_str, year_str = date_match.groups()
            month_num = _months.get(month_str.lower())
            if month_num:
                try:
                    decision_date = date(int(year_str), month_num, int(day_str))
                except ValueError:
                    pass

        title_tag = soup.find(["h1", "h2"])
        title = title_tag.get_text(" ", strip=True) if title_tag else (ecli or raw.source_id)

        return CanonicalCaseLaw(
            source="tribunal_constitucional",
            source_id=raw.source_id,
            jurisdiction="ES",
            type=doc_type,  # type: ignore[arg-type]
            title=title,
            publication_date=decision_date,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            ecli=ecli,
            court="Tribunal Constitucional de España",
            chamber=chamber,
            judges=judges,
            case_number=f"{number}/{year}" if number and year else "",
            decision_date=decision_date,
            anonymized=True,
        )
