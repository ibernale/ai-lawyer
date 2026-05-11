"""CENDOJ source — dev mode with rate limiting. ADR 0025.

Reference: docs/decisions/0025-cendoj-dev-mode.md
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalCaseLaw, RawDocument
from lex_agents_ingest.quota import QuotaTracker
from lex_agents_shared.exceptions import CendojSuspendedError

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_ECLI_RE = re.compile(r"ECLI:[A-Z]{2}:[A-Z]+:\d{4}:\d+")
_CASE_NUM_RE = re.compile(r"\b\d+/\d{4}\b")
_NORM_RE = re.compile(
    r"\b(?:Ley|Real Decreto(?:-[Ll]ey)?|Reglamento|Directiva|Decreto)\s[\d/\w-]+(?:/\d{4})?\b"
)
_FJ_RE = re.compile(
    r"FUNDAMENTO[S]?\s+JUR[IÍ]DICO[S]?\s+(?:N[ÚU]MERO\s+)?\w+",
    re.IGNORECASE,
)


class CendojSource(Source):
    """CENDOJ public search source with quota tracking. ADR 0025.

    In fixture mode (*fixture_path* is set), no network calls are made and quota
    is never consumed. In real mode the ``CENDOJ_CONTACT_EMAIL`` env var must be
    set; a ``QuotaTracker`` enforces the 50 req/day limit.
    """

    source_id = "cendoj"
    rate_limit_rps: float = 0.2  # 1 req / 5s

    BASE_URL = "https://www.poderjudicial.es/search/AN/"

    def __init__(
        self,
        quota_tracker: QuotaTracker | None = None,
        fixture_path: Path | None = None,
        contact_email: str | None = None,
    ) -> None:
        super().__init__()
        self._fixture_path = fixture_path

        if fixture_path is None:
            # Real mode — contact email required for polite User-Agent
            email = contact_email or os.environ.get("CENDOJ_CONTACT_EMAIL")
            if not email:
                raise RuntimeError(
                    "CENDOJ_CONTACT_EMAIL env var is required for real mode. "
                    "Set it to your institutional contact address. See ADR 0025."
                )
            self._headers = {
                "User-Agent": f"lex-agents/0.1 (legal-research-bot; +{email})",
                "X-Purpose": "legal-research-non-commercial",
            }
        else:
            self._headers = {}

        self._quota_tracker: QuotaTracker = quota_tracker or QuotaTracker()

    # ------------------------------------------------------------------
    # list_documents
    # ------------------------------------------------------------------

    async def list_documents(self, filters: dict | None = None) -> list[str]:  # type: ignore[override]
        """Return a list of document IDs.

        In fixture mode returns filenames from *fixture_path*. In real mode
        performs a paginated GET against the CENDOJ search endpoint.
        """
        if self._fixture_path is not None:
            return [p.stem for p in sorted(self._fixture_path.glob("*.html"))]

        # Real mode
        if self._quota_tracker.is_suspended():
            raise CendojSuspendedError("CENDOJ access suspended — manual reset required")
        self._quota_tracker.consume()

        import httpx
        from bs4 import BeautifulSoup

        params: dict[str, str] = {}
        if filters:
            params.update({k: str(v) for k, v in filters.items()})

        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "lxml")
        doc_ids: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if "openDocument" in href or "AN/" in href:
                slug = href.rstrip("/").split("/")[-1]
                if slug:
                    doc_ids.append(slug)
        return doc_ids

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    async def fetch(self, doc_id: str) -> RawDocument:
        """Return a RawDocument for *doc_id*.

        In fixture mode reads from *fixture_path*. In real mode fetches via HTTP
        and checks for captcha/rate-limit signals.
        """
        if self._fixture_path is not None:
            fixture_file = self._fixture_path / f"{doc_id}.html"
            raw_bytes = fixture_file.read_bytes()
            return RawDocument(
                source="cendoj",
                source_id=doc_id,
                raw_url=f"file://{fixture_file}",
                content_type="html",
                raw_bytes=raw_bytes,
                fetched_at=datetime.now(tz=timezone.utc),
            )

        # Real mode
        if self._quota_tracker.is_suspended():
            raise CendojSuspendedError("CENDOJ access suspended")
        self._quota_tracker.consume()

        import httpx

        url = f"{self.BASE_URL}{doc_id}"
        await self._rate_limiter.acquire()
        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            resp = await client.get(url)

        # Detect blocks / captcha
        if resp.status_code in (429, 403):
            reason = f"HTTP {resp.status_code}"
            self._quota_tracker.set_suspended(reason=reason)
            raise CendojSuspendedError(reason=reason)

        if resp.status_code >= 500:
            resp.raise_for_status()  # Let caller handle retry

        body_lower = resp.text.lower()
        if "captcha" in body_lower or "robot" in body_lower:
            reason = "captcha-detected"
            self._quota_tracker.set_suspended(reason=reason)
            raise CendojSuspendedError(reason=reason)

        return RawDocument(
            source="cendoj",
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
        """Parse a CENDOJ HTML document into a CanonicalCaseLaw."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw.raw_bytes, "lxml")
        full_text = soup.get_text("\n", strip=True)

        # --- ECLI ---
        ecli_match = _ECLI_RE.search(full_text)
        ecli = ecli_match.group(0) if ecli_match else None

        # --- Court & chamber ---
        court = ""
        chamber = None
        header_tag = soup.find(["h1", "h2", "header"])
        if header_tag:
            header_text = header_tag.get_text(" ", strip=True)
            court = header_text
            # Try to detect sala/sección from header
            sala_match = re.search(r"(Sala\s+\w+(?:\s+de\s+lo\s+\w+)?)", header_text, re.I)
            if sala_match:
                chamber = sala_match.group(1)

        if not court:
            # Fallback: first meaningful paragraph
            for tag in soup.find_all(["p", "div"], limit=5):
                txt = tag.get_text(" ", strip=True)
                if txt and len(txt) > 10:
                    court = txt[:120]
                    break

        # --- Judges ---
        judges: list[str] = []
        ponente_match = re.search(
            r"(?:Ponente|Magistrado ponente)[:\s]+([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s,]+)",
            full_text,
        )
        if ponente_match:
            judges = [ponente_match.group(1).strip()]

        # --- Case number ---
        case_number = ""
        cn_match = _CASE_NUM_RE.search(full_text)
        if cn_match:
            case_number = cn_match.group(0)

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

        # --- Operative part (fallo) ---
        operative_part = ""
        fallo_match = re.search(
            r"(?:FALLO|Fallo)[:\s]+(.*?)(?=\n{2,}|FUNDAMENTO|$)",
            full_text,
            re.DOTALL,
        )
        if fallo_match:
            operative_part = fallo_match.group(1).strip()[:2000]

        # --- Grounds (Fundamentos Jurídicos) ---
        grounds: list[str] = []
        fj_parts = re.split(
            r"FUNDAMENTO[S]?\s+JURI[DÍ]ICO[S]?\s*(?:N[ÚU]MERO\s+)?\w*\.?\s*",
            full_text,
            flags=re.IGNORECASE,
        )
        for part in fj_parts[1:]:
            ground = part.strip()[:1000]
            if ground:
                grounds.append(ground)

        # --- Related norms ---
        related_norms = list(dict.fromkeys(_NORM_RE.findall(full_text)))

        # --- Title ---
        title = ecli or raw.source_id

        return CanonicalCaseLaw(
            source="cendoj",
            source_id=raw.source_id,
            jurisdiction="ES",
            type="sentencia",
            title=title,
            publication_date=decision_date,
            full_text=full_text,
            raw_url=raw.raw_url,
            fetched_at=raw.fetched_at,
            ecli=ecli,
            court=court,
            chamber=chamber,
            judges=judges,
            case_number=case_number,
            decision_date=decision_date,
            operative_part=operative_part,
            grounds=grounds,
            related_norms=related_norms,
            anonymized=True,
        )
