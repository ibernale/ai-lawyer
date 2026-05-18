"""EBA regulatory calendar source.

Scrapes the EBA public calendar at https://www.eba.europa.eu/calendar to
extract upcoming consultation deadlines, application dates and publication
milestones.

The page is server-rendered HTML with a table/list of events; we parse
`<article>` or `<li>` blocks that contain a date + title + (optional) link.

Rate limit: 0.25 rps (1 req / 4 s) — EBA has no public rate-limit policy
but their CDN will 429 on bursts. Calendar fetches are rare (≤ 1/day).
"""

from __future__ import annotations

import re
from datetime import date

import httpx
import structlog
from lxml import etree  # type: ignore[import-untyped]

from lex_agents_ingest.base import Source
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_EBA_CALENDAR_URL = "https://www.eba.europa.eu/calendar"
_ESMA_CALENDAR_URL = "https://www.esma.europa.eu/press-news/esma-news?doc_type=20"

# Regex to find ISO-like dates in text: DD/MM/YYYY, YYYY-MM-DD, DD Month YYYY
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),           # 2024-12-31
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),        # 31/12/2024
    re.compile(
        r"\b(\d{1,2})\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+(\d{4})\b",
        re.IGNORECASE,
    ),
]

_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _parse_date(text: str) -> date | None:
    """Extract the first recognisable date from *text*. Returns None on failure."""
    m = _DATE_PATTERNS[0].search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    m = _DATE_PATTERNS[1].search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    m = _DATE_PATTERNS[2].search(text)
    if m:
        try:
            month = _MONTH_MAP.get(m.group(2).lower(), 0)
            return date(int(m.group(3)), month, int(m.group(1)))
        except ValueError:
            pass

    return None


def _parse_deadline_type(title: str) -> str:
    """Heuristic deadline type from title text."""
    tl = title.lower()
    if any(w in tl for w in ("consultation", "consulta", "cp/")):
        return "consultation"
    if any(w in tl for w in ("application", "aplicaci", "entry into force", "entrada en vigor")):
        return "application"
    # "reporting" must be checked before "report" to avoid matching "final report"
    if any(w in tl for w in ("reporting", "remisión")):
        return "reporting"
    if any(w in tl for w in ("review", "revisión")):
        return "review"
    if any(w in tl for w in ("publication", "publicaci", "final report", "informe")):
        return "publication"
    return "other"


def _extract_events_from_html(html: bytes, base_url: str, source_id: str) -> list[dict]:
    """Parse EBA/ESMA HTML and return a list of raw event dicts."""
    events: list[dict] = []
    try:
        parser = etree.HTMLParser()
        root = etree.fromstring(html, parser)
    except Exception:
        logger.warning("eba_calendar_parse_error")
        return events

    # Strategy 1: look for elements with date-looking meta attributes
    # EBA uses <span class="date-display-single"> or <time datetime="...">
    for time_el in root.iter("time"):
        dt_attr = time_el.get("datetime", "")
        title_el = time_el.getparent()
        if title_el is None:
            continue
        # itertext() is available on all lxml._Element objects (text_content() is lxml.html only)
        title = " ".join(title_el.itertext()).strip()
        if not title:
            continue
        event_date = _parse_date(dt_attr) or _parse_date(title)
        if event_date:
            # Find nearest anchor for URL
            url: str | None = None
            for a in (title_el.iter("a") if title_el is not None else []):
                href = a.get("href", "")
                if href:
                    url = href if href.startswith("http") else base_url.rstrip("/") + href
                    break
            events.append({
                "title": title[:200],
                "event_date": event_date,
                "url": url,
                "source_id": source_id,
            })

    # Strategy 2: look for <a> elements whose text contains a date pattern and look like events
    if not events:
        for a in root.iter("a"):
            href = a.get("href", "")
            text = (a.text or "").strip()
            if len(text) < 10:
                continue
            event_date = _parse_date(text)
            if event_date:
                url = href if href.startswith("http") else base_url.rstrip("/") + href
                events.append({
                    "title": text[:200],
                    "event_date": event_date,
                    "url": url,
                    "source_id": source_id,
                })

    return events


class EbaCalendarSource(Source):
    """EBA regulatory calendar — consultation deadlines and application dates."""

    source_id = "eba_calendar"
    rate_limit_rps: float = 0.25

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._client = http_client or httpx.AsyncClient(timeout=30)

    async def list_documents(self) -> list[str]:
        """Return synthetic IDs — for change-monitor compatibility. Not used for calendar."""
        return []

    async def fetch_calendar(self) -> list[dict]:
        """Fetch and parse the EBA calendar page. Returns list of raw event dicts."""
        try:
            resp = await self._client.get(_EBA_CALENDAR_URL)
            resp.raise_for_status()
        except Exception:
            logger.exception("eba_calendar_fetch_error", url=_EBA_CALENDAR_URL)
            return []
        return _extract_events_from_html(resp.content, _EBA_CALENDAR_URL, self.source_id)

    async def fetch(self, doc_id: str) -> RawDocument:
        """Not used — calendar source does not index individual documents."""
        raise NotImplementedError("EbaCalendarSource.fetch() is not supported")

    async def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        raise NotImplementedError("EbaCalendarSource.parse_to_canonical() is not supported")
