"""Unit tests for InlabsDOUSource using local fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from lex_agents_ingest.canonical import CanonicalBulletin, RawDocument
from lex_agents_ingest.sources.inlabs_dou import InlabsDOUSource

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "inlabs"


@pytest.fixture
def inlabs_source() -> InlabsDOUSource:
    return InlabsDOUSource(fixture_path=FIXTURE_DIR)


@pytest.fixture
def fixture_raw() -> RawDocument:
    fixture_file = FIXTURE_DIR / "dou_20240115.xml"
    raw_bytes = fixture_file.read_bytes()
    from datetime import datetime, timezone
    return RawDocument(
        source="inlabs_dou",
        source_id="dou_20240115",
        raw_url=f"file://{fixture_file}",
        content_type="xml",
        raw_bytes=raw_bytes,
        fetched_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.unit
def test_parse_extracts_autoridade(
    inlabs_source: InlabsDOUSource, fixture_raw: RawDocument
) -> None:
    result = inlabs_source.parse_to_canonical(fixture_raw)
    assert isinstance(result, CanonicalBulletin)
    assert result.issuing_authority == "Banco Central do Brasil"


@pytest.mark.unit
def test_parse_extracts_ementa(
    inlabs_source: InlabsDOUSource, fixture_raw: RawDocument
) -> None:
    result = inlabs_source.parse_to_canonical(fixture_raw)
    assert result.summary is not None
    assert "instituições financeiras" in result.summary


@pytest.mark.unit
def test_bulletin_is_dou(
    inlabs_source: InlabsDOUSource, fixture_raw: RawDocument
) -> None:
    result = inlabs_source.parse_to_canonical(fixture_raw)
    assert result.bulletin == "DOU"


@pytest.mark.unit
def test_language_is_pt_br(
    inlabs_source: InlabsDOUSource, fixture_raw: RawDocument
) -> None:
    result = inlabs_source.parse_to_canonical(fixture_raw)
    assert result.extra.get("language") == "pt-BR"


@pytest.mark.unit
def test_jurisdiction_is_br(
    inlabs_source: InlabsDOUSource, fixture_raw: RawDocument
) -> None:
    result = inlabs_source.parse_to_canonical(fixture_raw)
    assert result.jurisdiction == "BR"


@pytest.mark.unit
def test_missing_token_raises_on_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INLABS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="INLABS_TOKEN"):
        InlabsDOUSource()


@pytest.mark.unit
async def test_fixture_list_documents(inlabs_source: InlabsDOUSource) -> None:
    doc_ids = await inlabs_source.list_documents()
    assert "dou_20240115" in doc_ids
