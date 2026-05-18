"""Unit tests for CalendarEventStore, CalendarSyncer, and EbaCalendarSource helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from lex_agents_ingest.calendar_store import CalendarEvent, CalendarEventStore, CalendarSyncer
from lex_agents_ingest.sources.eba_calendar import (
    _extract_events_from_html,
    _parse_date,
    _parse_deadline_type,
)

# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("2024-12-31", date(2024, 12, 31)),
        ("31/12/2024", date(2024, 12, 31)),
        ("15 March 2025", date(2025, 3, 15)),
        ("1 january 2026", date(2026, 1, 1)),
        ("no date here", None),
        ("", None),
    ],
)
def test_parse_date(text: str, expected: date | None) -> None:
    assert _parse_date(text) == expected


# ---------------------------------------------------------------------------
# _parse_deadline_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Consultation Paper CP/2024/01", "consultation"),
        ("Entry into force of CRR3", "application"),
        ("COREP reporting deadline", "reporting"),
        ("Review of internal models", "review"),
        ("Publication of final report", "publication"),
        ("EBA Board meeting", "other"),
    ],
)
def test_parse_deadline_type(title: str, expected: str) -> None:
    assert _parse_deadline_type(title) == expected


# ---------------------------------------------------------------------------
# _extract_events_from_html
# ---------------------------------------------------------------------------

_SAMPLE_HTML = b"""
<html>
<body>
  <article>
    <time datetime="2025-06-30">30 June 2025</time>
    <h3><a href="/eba/consultation-crr3">Consultation on CRR3 technical standards</a></h3>
  </article>
  <article>
    <time datetime="2025-09-15">15 September 2025</time>
    <h3><a href="/eba/application-dora">DORA application date</a></h3>
  </article>
  <article>
    <time datetime="">No date article</time>
    <h3>Article without date</h3>
  </article>
</body>
</html>
"""


def test_extract_events_from_html_finds_events() -> None:
    events = _extract_events_from_html(_SAMPLE_HTML, "https://www.eba.europa.eu", "eba_calendar")
    dates = {e["event_date"] for e in events}
    assert date(2025, 6, 30) in dates
    assert date(2025, 9, 15) in dates


def test_extract_events_from_html_empty_html() -> None:
    events = _extract_events_from_html(b"<html><body></body></html>", "https://x.eu", "eba_calendar")
    assert events == []


def test_extract_events_from_html_bad_html() -> None:
    events = _extract_events_from_html(b"not html at all !@#$", "https://x.eu", "eba_calendar")
    # Must not raise — returns empty or partial
    assert isinstance(events, list)


# ---------------------------------------------------------------------------
# CalendarEventStore
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    return str(tmp_path / "test_calendar.db")


@pytest.mark.asyncio
async def test_store_init(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()


@pytest.mark.asyncio
async def test_store_save_and_list(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    event = CalendarEvent(
        title="Consultation Paper CP/2024/01",
        event_date=date(2025, 6, 30),
        deadline_type="consultation",
        source_id="eba_calendar",
        url="https://eba.europa.eu/cp2024-01",
        domain="regulatorio_bancario_ue_es",
        jurisdiction="EU",
    )
    await store.save_event(event)

    events = await store.list_events()
    assert len(events) == 1
    assert events[0].title == "Consultation Paper CP/2024/01"
    assert events[0].deadline_type == "consultation"


@pytest.mark.asyncio
async def test_store_save_upserts(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    event = CalendarEvent(
        id="fixed-id",
        title="Original title",
        event_date=date(2025, 6, 30),
        source_id="eba_calendar",
    )
    await store.save_event(event)

    updated = event.model_copy(update={"title": "Updated title"})
    await store.save_event(updated)

    events = await store.list_events()
    assert len(events) == 1
    assert events[0].title == "Updated title"


@pytest.mark.asyncio
async def test_store_list_date_filter(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    past = CalendarEvent(title="Past", event_date=date(2024, 1, 1), source_id="eba_calendar")
    future = CalendarEvent(title="Future", event_date=date(2026, 12, 31), source_id="eba_calendar")
    await store.save_event(past)
    await store.save_event(future)

    events = await store.list_events(from_date=date(2025, 1, 1))
    assert len(events) == 1
    assert events[0].title == "Future"


@pytest.mark.asyncio
async def test_store_list_deadline_type_filter(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    e1 = CalendarEvent(
        title="Consultation", event_date=date(2025, 6, 1),
        deadline_type="consultation", source_id="eba_calendar",
    )
    e2 = CalendarEvent(
        title="Reporting", event_date=date(2025, 7, 1),
        deadline_type="reporting", source_id="eba_calendar",
    )
    await store.save_event(e1)
    await store.save_event(e2)

    consultations = await store.list_events(deadline_type="consultation")
    assert len(consultations) == 1
    assert consultations[0].title == "Consultation"


@pytest.mark.asyncio
async def test_store_upcoming(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    today = datetime.now(UTC).date()
    soon = CalendarEvent(
        title="Soon", event_date=today + timedelta(days=7), source_id="eba_calendar"
    )
    far = CalendarEvent(
        title="Far", event_date=today + timedelta(days=365), source_id="eba_calendar"
    )
    past = CalendarEvent(
        title="Past", event_date=today - timedelta(days=1), source_id="eba_calendar"
    )
    await store.save_event(soon)
    await store.save_event(far)
    await store.save_event(past)

    upcoming = await store.upcoming(days=30)
    titles = {e.title for e in upcoming}
    assert "Soon" in titles
    assert "Far" not in titles
    assert "Past" not in titles


@pytest.mark.asyncio
async def test_store_count(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    for i in range(5):
        await store.save_event(
            CalendarEvent(title=f"Event {i}", event_date=date(2025, i + 1, 1), source_id="eba_calendar")
        )

    assert await store.count() == 5


@pytest.mark.asyncio
async def test_store_empty_list(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()
    events = await store.list_events()
    assert events == []


# ---------------------------------------------------------------------------
# CalendarSyncer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_syncer_sync_stores_events(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    raw_events = [
        {
            "title": "Consultation Paper CP/2025/01",
            "event_date": date(2025, 9, 30),
            "url": "https://eba.europa.eu/cp2025",
            "source_id": "eba_calendar",
        },
        {
            "title": "DORA application date",
            "event_date": date(2025, 1, 17),
            "url": None,
            "source_id": "eba_calendar",
        },
    ]

    mock_source = AsyncMock()
    mock_source.fetch_calendar = AsyncMock(return_value=raw_events)
    syncer = CalendarSyncer(store, source=mock_source)
    n = await syncer.sync()

    assert n == 2
    events = await store.list_events()
    assert len(events) == 2
    titles = {e.title for e in events}
    assert "Consultation Paper CP/2025/01" in titles


@pytest.mark.asyncio
async def test_syncer_sync_empty_source(tmp_db: str) -> None:
    store = CalendarEventStore(tmp_db)
    await store.init()

    mock_source = AsyncMock()
    mock_source.fetch_calendar = AsyncMock(return_value=[])
    syncer = CalendarSyncer(store, source=mock_source)
    n = await syncer.sync()

    assert n == 0
    assert await store.count() == 0
