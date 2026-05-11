"""Unit tests for CendojSource using local fixtures. ADR 0025."""

from __future__ import annotations

from pathlib import Path

import pytest

from lex_agents_ingest.canonical import CanonicalCaseLaw, RawDocument
from lex_agents_ingest.quota import QuotaTracker
from lex_agents_ingest.sources.cendoj import CendojSource
from lex_agents_shared.exceptions import CendojSuspendedError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cendoj"


@pytest.fixture
def fixture_source(tmp_path: Path) -> CendojSource:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    return CendojSource(quota_tracker=tracker, fixture_path=FIXTURE_DIR)


@pytest.fixture
def fixture_raw(fixture_source: CendojSource) -> RawDocument:
    fixture_file = FIXTURE_DIR / "STS_12345_2024.html"
    raw_bytes = fixture_file.read_bytes()
    from datetime import datetime, timezone
    return RawDocument(
        source="cendoj",
        source_id="STS_12345_2024",
        raw_url=f"file://{fixture_file}",
        content_type="html",
        raw_bytes=raw_bytes,
        fetched_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.unit
def test_parse_to_canonical_extracts_ecli(
    fixture_source: CendojSource, fixture_raw: RawDocument
) -> None:
    result = fixture_source.parse_to_canonical(fixture_raw)
    assert isinstance(result, CanonicalCaseLaw)
    assert result.ecli == "ECLI:ES:TS:2024:12345"


@pytest.mark.unit
def test_parse_to_canonical_extracts_court(
    fixture_source: CendojSource, fixture_raw: RawDocument
) -> None:
    result = fixture_source.parse_to_canonical(fixture_raw)
    assert result.court != ""
    assert "TRIBUNAL SUPREMO" in result.court.upper() or "Sala" in result.court


@pytest.mark.unit
def test_parse_to_canonical_extracts_case_number(
    fixture_source: CendojSource, fixture_raw: RawDocument
) -> None:
    result = fixture_source.parse_to_canonical(fixture_raw)
    assert result.case_number != ""
    # Should contain a pattern like NNN/YYYY
    assert "/" in result.case_number


@pytest.mark.unit
def test_parse_to_canonical_anonymized_true(
    fixture_source: CendojSource, fixture_raw: RawDocument
) -> None:
    result = fixture_source.parse_to_canonical(fixture_raw)
    assert result.anonymized is True


@pytest.mark.unit
async def test_fixture_mode_does_not_consume_quota(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    source = CendojSource(quota_tracker=tracker, fixture_path=FIXTURE_DIR)
    initial_remaining = tracker.get_remaining()
    doc_ids = await source.list_documents()
    assert tracker.get_remaining() == initial_remaining
    assert "STS_12345_2024" in doc_ids


@pytest.mark.unit
async def test_suspended_raises_on_real_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CENDOJ_CONTACT_EMAIL", "test@example.com")
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    tracker.set_suspended(reason="test-suspension")
    source = CendojSource(quota_tracker=tracker)
    with pytest.raises(CendojSuspendedError):
        await source.list_documents()


@pytest.mark.unit
def test_source_id_is_cendoj(fixture_source: CendojSource) -> None:
    assert fixture_source.source_id == "cendoj"


@pytest.mark.unit
def test_parse_full_text_is_populated(
    fixture_source: CendojSource, fixture_raw: RawDocument
) -> None:
    result = fixture_source.parse_to_canonical(fixture_raw)
    assert len(result.full_text) > 100
    assert "TRIBUNAL SUPREMO" in result.full_text
