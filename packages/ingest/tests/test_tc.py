"""Unit tests for TribunalConstitucionalSource using local fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from lex_agents_ingest.canonical import CanonicalCaseLaw, RawDocument
from lex_agents_ingest.sources.tribunal_constitucional import TribunalConstitucionalSource

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tc"


@pytest.fixture
def tc_source() -> TribunalConstitucionalSource:
    return TribunalConstitucionalSource(fixture_path=FIXTURE_DIR)


@pytest.fixture
def fixture_raw() -> RawDocument:
    fixture_file = FIXTURE_DIR / "STC_45_2023.html"
    raw_bytes = fixture_file.read_bytes()
    from datetime import datetime, timezone
    return RawDocument(
        source="tribunal_constitucional",
        source_id="STC_45_2023",
        raw_url=f"file://{fixture_file}",
        content_type="html",
        raw_bytes=raw_bytes,
        fetched_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.unit
def test_parse_returns_canonical_case_law(
    tc_source: TribunalConstitucionalSource, fixture_raw: RawDocument
) -> None:
    result = tc_source.parse_to_canonical(fixture_raw)
    assert isinstance(result, CanonicalCaseLaw)


@pytest.mark.unit
def test_source_is_tribunal_constitucional(
    tc_source: TribunalConstitucionalSource, fixture_raw: RawDocument
) -> None:
    result = tc_source.parse_to_canonical(fixture_raw)
    assert result.source == "tribunal_constitucional"


@pytest.mark.unit
def test_jurisdiction_is_es(
    tc_source: TribunalConstitucionalSource, fixture_raw: RawDocument
) -> None:
    result = tc_source.parse_to_canonical(fixture_raw)
    assert result.jurisdiction == "ES"


@pytest.mark.unit
def test_ecli_extracted(
    tc_source: TribunalConstitucionalSource, fixture_raw: RawDocument
) -> None:
    result = tc_source.parse_to_canonical(fixture_raw)
    assert result.ecli == "ECLI:ES:TC:2023:45"


@pytest.mark.unit
def test_court_is_tribunal_constitucional(
    tc_source: TribunalConstitucionalSource, fixture_raw: RawDocument
) -> None:
    result = tc_source.parse_to_canonical(fixture_raw)
    assert "Constitucional" in result.court


@pytest.mark.unit
def test_chamber_detected(
    tc_source: TribunalConstitucionalSource, fixture_raw: RawDocument
) -> None:
    result = tc_source.parse_to_canonical(fixture_raw)
    assert result.chamber is not None
    assert "Pleno" in result.chamber


@pytest.mark.unit
async def test_fixture_list_documents(tc_source: TribunalConstitucionalSource) -> None:
    doc_ids = await tc_source.list_documents()
    assert "STC_45_2023" in doc_ids
