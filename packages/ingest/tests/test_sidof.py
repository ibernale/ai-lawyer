"""Unit tests for SidofDOFSource using local fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from lex_agents_ingest.canonical import CanonicalBulletin, RawDocument
from lex_agents_ingest.sources.sidof_dof import SidofDOFSource

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sidof"


@pytest.fixture
def sidof_source() -> SidofDOFSource:
    return SidofDOFSource(fixture_path=FIXTURE_DIR)


@pytest.fixture
def fixture_raw() -> RawDocument:
    fixture_file = FIXTURE_DIR / "dof_nota_cnbv.html"
    raw_bytes = fixture_file.read_bytes()
    from datetime import datetime, timezone
    return RawDocument(
        source="sidof_dof",
        source_id="dof_nota_cnbv",
        raw_url=f"file://{fixture_file}",
        content_type="html",
        raw_bytes=raw_bytes,
        fetched_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.unit
def test_parse_extracts_authority(
    sidof_source: SidofDOFSource, fixture_raw: RawDocument
) -> None:
    result = sidof_source.parse_to_canonical(fixture_raw)
    assert isinstance(result, CanonicalBulletin)
    assert result.issuing_authority == "CNBV"


@pytest.mark.unit
def test_bulletin_is_dof(
    sidof_source: SidofDOFSource, fixture_raw: RawDocument
) -> None:
    result = sidof_source.parse_to_canonical(fixture_raw)
    assert result.bulletin == "DOF"


@pytest.mark.unit
def test_language_is_es_mx(
    sidof_source: SidofDOFSource, fixture_raw: RawDocument
) -> None:
    result = sidof_source.parse_to_canonical(fixture_raw)
    assert result.extra.get("language") == "es-MX"


@pytest.mark.unit
def test_jurisdiction_is_mx(
    sidof_source: SidofDOFSource, fixture_raw: RawDocument
) -> None:
    result = sidof_source.parse_to_canonical(fixture_raw)
    assert result.jurisdiction == "MX"


@pytest.mark.unit
def test_full_text_populated(
    sidof_source: SidofDOFSource, fixture_raw: RawDocument
) -> None:
    result = sidof_source.parse_to_canonical(fixture_raw)
    assert len(result.full_text) > 50
    assert "CNBV" in result.full_text


@pytest.mark.unit
async def test_fixture_list_documents(sidof_source: SidofDOFSource) -> None:
    doc_ids = await sidof_source.list_documents()
    assert "dof_nota_cnbv" in doc_ids
