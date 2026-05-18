"""Unit tests for ChangeMonitor, ChangeEventStore, and severity heuristic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from lex_agents_ingest.change_monitor import (
    ChangeEvent,
    ChangeEventStore,
    ChangeMonitor,
    classify_severity,
)

# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected",
    [
        ("New Regulation on Capital Requirements", "high"),
        ("Ley de servicios de pago", "high"),
        ("Directive on AML compliance", "high"),
        ("Circular 2/2024 del Banco de España", "medium"),
        ("Guidance on internal model validation", "medium"),
        ("Norma técnica EBA/GL/2024/01", "medium"),
        ("Publicación BOE-A-2024-12345", "low"),
        ("Working paper BIS #123", "low"),
    ],
)
def test_classify_severity(title: str, expected: str) -> None:
    assert classify_severity(title) == expected


# ---------------------------------------------------------------------------
# ChangeEventStore — in-memory via tmp file
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    return str(tmp_path / "test_monitor.db")


@pytest.mark.asyncio
async def test_store_init_creates_tables(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()
    # No error = DDL succeeded


@pytest.mark.asyncio
async def test_store_is_known_false_initially(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()
    assert not await store.is_known("boe", "BOE-A-2024-001")


@pytest.mark.asyncio
async def test_store_mark_seen_makes_known(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()
    await store.mark_seen("boe", "BOE-A-2024-001")
    assert await store.is_known("boe", "BOE-A-2024-001")


@pytest.mark.asyncio
async def test_store_mark_seen_idempotent(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()
    await store.mark_seen("boe", "BOE-A-2024-001")
    await store.mark_seen("boe", "BOE-A-2024-001")  # second call must not raise
    assert await store.is_known("boe", "BOE-A-2024-001")


@pytest.mark.asyncio
async def test_store_save_and_list_events(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    event = ChangeEvent(
        source_id="boe",
        document_id="BOE-A-2024-001",
        title="Ley 1/2024",
        severity="high",
        domain="regulatorio_bancario_ue_es",
    )
    await store.save_event(event)

    events = await store.list_events()
    assert len(events) == 1
    assert events[0].document_id == "BOE-A-2024-001"
    assert events[0].severity == "high"


@pytest.mark.asyncio
async def test_store_list_events_unread_filter(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    e1 = ChangeEvent(source_id="boe", document_id="doc1", title="doc1", read=False)
    e2 = ChangeEvent(source_id="boe", document_id="doc2", title="doc2", read=True)
    await store.save_event(e1)
    await store.save_event(e2)

    unread = await store.list_events(unread_only=True)
    assert len(unread) == 1
    assert unread[0].document_id == "doc1"


@pytest.mark.asyncio
async def test_store_list_events_severity_filter(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    e1 = ChangeEvent(source_id="boe", document_id="doc1", title="d1", severity="high")
    e2 = ChangeEvent(source_id="boe", document_id="doc2", title="d2", severity="low")
    await store.save_event(e1)
    await store.save_event(e2)

    highs = await store.list_events(severity="high")
    assert len(highs) == 1
    assert highs[0].document_id == "doc1"


@pytest.mark.asyncio
async def test_store_mark_read(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    event = ChangeEvent(source_id="boe", document_id="doc1", title="d1", read=False)
    await store.save_event(event)

    found = await store.mark_read(event.id)
    assert found is True

    events = await store.list_events(unread_only=True)
    assert len(events) == 0


@pytest.mark.asyncio
async def test_store_mark_read_not_found(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()
    found = await store.mark_read("nonexistent-id")
    assert found is False


@pytest.mark.asyncio
async def test_store_unread_count(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    for i in range(3):
        await store.save_event(
            ChangeEvent(source_id="boe", document_id=f"doc{i}", title=f"d{i}", read=False)
        )
    await store.save_event(
        ChangeEvent(source_id="boe", document_id="doc_read", title="read", read=True)
    )

    assert await store.unread_count() == 3


@pytest.mark.asyncio
async def test_store_save_event_idempotent(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    event = ChangeEvent(source_id="boe", document_id="doc1", title="d1")
    await store.save_event(event)
    await store.save_event(event)  # INSERT OR IGNORE — must not raise

    events = await store.list_events()
    assert len(events) == 1


# ---------------------------------------------------------------------------
# ChangeMonitor
# ---------------------------------------------------------------------------

def _make_source(source_id: str, doc_ids: list[str]) -> MagicMock:
    source = MagicMock()
    source.source_id = source_id
    source.list_documents = AsyncMock(return_value=doc_ids)
    return source


@pytest.mark.asyncio
async def test_monitor_scan_new_documents(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    source = _make_source("boe", ["BOE-A-2024-001", "BOE-A-2024-002"])
    monitor = ChangeMonitor([source], store)

    events = await monitor.scan()
    assert len(events) == 2
    doc_ids = {e.document_id for e in events}
    assert doc_ids == {"BOE-A-2024-001", "BOE-A-2024-002"}


@pytest.mark.asyncio
async def test_monitor_scan_skips_known_documents(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    # Pre-seed checkpoint
    await store.mark_seen("boe", "BOE-A-2024-001")

    source = _make_source("boe", ["BOE-A-2024-001", "BOE-A-2024-002"])
    monitor = ChangeMonitor([source], store)

    events = await monitor.scan()
    assert len(events) == 1
    assert events[0].document_id == "BOE-A-2024-002"


@pytest.mark.asyncio
async def test_monitor_scan_second_run_finds_nothing(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    source = _make_source("boe", ["BOE-A-2024-001"])
    monitor = ChangeMonitor([source], store)

    first = await monitor.scan()
    assert len(first) == 1

    second = await monitor.scan()
    assert len(second) == 0


@pytest.mark.asyncio
async def test_monitor_scan_multiple_sources(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    boe = _make_source("boe", ["BOE-001"])
    eurlex = _make_source("eurlex", ["EUR-001", "EUR-002"])
    monitor = ChangeMonitor([boe, eurlex], store)

    events = await monitor.scan()
    assert len(events) == 3
    sources = {e.source_id for e in events}
    assert sources == {"boe", "eurlex"}


@pytest.mark.asyncio
async def test_monitor_scan_source_error_continues(tmp_db: str) -> None:
    """A source that raises on list_documents should not abort the scan."""
    store = ChangeEventStore(tmp_db)
    await store.init()

    broken = MagicMock()
    broken.source_id = "broken"
    broken.list_documents = AsyncMock(side_effect=RuntimeError("network error"))

    good = _make_source("boe", ["BOE-001"])
    monitor = ChangeMonitor([broken, good], store)

    events = await monitor.scan()
    assert len(events) == 1
    assert events[0].source_id == "boe"


@pytest.mark.asyncio
async def test_monitor_scan_events_persisted(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    source = _make_source("boe", ["BOE-001"])
    monitor = ChangeMonitor([source], store)

    await monitor.scan()

    stored = await store.list_events()
    assert len(stored) == 1
    assert stored[0].source_id == "boe"


@pytest.mark.asyncio
async def test_monitor_scan_domain_mapping(tmp_db: str) -> None:
    store = ChangeEventStore(tmp_db)
    await store.init()

    sepblac = _make_source("sepblac", ["SEPBLAC-001"])
    monitor = ChangeMonitor([sepblac], store)

    events = await monitor.scan()
    assert events[0].domain == "aml_compliance"
