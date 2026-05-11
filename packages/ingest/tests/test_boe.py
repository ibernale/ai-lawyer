"""Tests for BoeSource using local fixtures."""

from __future__ import annotations

import pytest
import respx
import httpx
from pathlib import Path

from lex_agents_ingest.sources.boe import BoeSource
from lex_agents_ingest.canonical import CanonicalDocument

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "boe"


@pytest.fixture
def boe_source() -> BoeSource:
    client = httpx.AsyncClient()
    return BoeSource(http_client=client)


class TestFetchReturnsRawDocument:
    @pytest.mark.asyncio
    async def test_fetch_returns_raw_document(self, boe_source: BoeSource) -> None:
        fixture = (FIXTURE_DIR / "BOE-A-2014-6732.xml").read_bytes()
        with respx.mock:
            respx.get(
                "https://boe.es/diario_boe/xml.php?id=BOE-A-2014-6732"
            ).mock(return_value=httpx.Response(200, content=fixture))
            raw = await boe_source.fetch("BOE-A-2014-6732")
        assert raw.source_id == "BOE-A-2014-6732"
        assert raw.content_type == "xml"
        assert len(raw.raw_bytes) > 0
        assert raw.checksum != ""


class TestParseLeyProducesCanonical:
    def test_parse_ley_produces_canonical(self, boe_source: BoeSource) -> None:
        fixture = (FIXTURE_DIR / "BOE-A-2014-6732.xml").read_bytes()
        from lex_agents_ingest.canonical import RawDocument
        raw = RawDocument(
            source="boe",
            source_id="BOE-A-2014-6732",
            raw_url="https://boe.es/diario_boe/xml.php?id=BOE-A-2014-6732",
            content_type="xml",
            raw_bytes=fixture,
        )
        doc = boe_source.parse_to_canonical(raw)
        assert isinstance(doc, CanonicalDocument)
        assert doc.source == "boe"
        assert doc.jurisdiction == "ES"
        assert doc.type == "ley"
        assert "Ley 10/2014" in doc.title
        assert doc.publication_date.year == 2014
        assert len(doc.hierarchy) > 0
        assert doc.full_text != ""

    def test_parse_real_decreto_type(self, boe_source: BoeSource) -> None:
        fixture = (FIXTURE_DIR / "BOE-A-2015-1510.xml").read_bytes()
        from lex_agents_ingest.canonical import RawDocument
        raw = RawDocument(
            source="boe",
            source_id="BOE-A-2015-1510",
            raw_url="https://boe.es/diario_boe/xml.php?id=BOE-A-2015-1510",
            content_type="xml",
            raw_bytes=fixture,
        )
        doc = boe_source.parse_to_canonical(raw)
        assert doc.type == "real_decreto"


class TestChecksumStability:
    def test_checksum_stability(self, boe_source: BoeSource) -> None:
        from lex_agents_ingest.canonical import RawDocument
        fixture = (FIXTURE_DIR / "BOE-A-2014-6732.xml").read_bytes()
        raw = RawDocument(
            source="boe",
            source_id="BOE-A-2014-6732",
            raw_url="https://boe.es/diario_boe/xml.php?id=BOE-A-2014-6732",
            content_type="xml",
            raw_bytes=fixture,
        )
        doc1 = boe_source.parse_to_canonical(raw)
        doc2 = boe_source.parse_to_canonical(raw)
        assert doc1.checksum == doc2.checksum
        assert doc1.checksum != ""
