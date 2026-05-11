"""Tests for EurlexSource using local fixtures."""

from __future__ import annotations

import pytest
import respx
import httpx
from pathlib import Path

from lex_agents_ingest.sources.eurlex import EurlexSource
from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "eurlex"


@pytest.fixture
def eurlex_source() -> EurlexSource:
    client = httpx.AsyncClient()
    return EurlexSource(http_client=client)


class TestFetchEurlexRawDocument:
    @pytest.mark.asyncio
    async def test_fetch_returns_raw_document(self, eurlex_source: EurlexSource) -> None:
        fixture = (FIXTURE_DIR / "32013R0575.xml").read_bytes()
        with respx.mock:
            # Mock SPARQL endpoint
            respx.post(
                "https://publications.europa.eu/webapi/rdf/sparql"
            ).mock(return_value=httpx.Response(
                200,
                json={"results": {"bindings": [
                    {"work": {"value": "https://publications.europa.eu/resource/cellar/abc123"}}
                ]}}
            ))
            # Mock Cellar fetch
            respx.get(
                "https://publications.europa.eu/resource/cellar/abc123"
            ).mock(return_value=httpx.Response(200, content=fixture))
            raw = await eurlex_source.fetch("32013R0575")
        assert raw.source_id == "32013R0575"
        assert raw.content_type == "xml"
        assert len(raw.raw_bytes) > 0


class TestParseRegulationProducesCanonical:
    def test_parse_regulation_produces_canonical(self, eurlex_source: EurlexSource) -> None:
        fixture = (FIXTURE_DIR / "32013R0575.xml").read_bytes()
        raw = RawDocument(
            source="eurlex",
            source_id="32013R0575",
            raw_url="https://eur-lex.europa.eu/legal-content/ES/TXT/XML/?uri=CELEX:32013R0575",
            content_type="xml",
            raw_bytes=fixture,
        )
        doc = eurlex_source.parse_to_canonical(raw)
        assert isinstance(doc, CanonicalDocument)
        assert doc.source == "eurlex"
        assert doc.jurisdiction == "EU"
        assert doc.type == "regulation"
        assert len(doc.hierarchy) > 0
        assert doc.full_text != ""

    def test_parse_directive_type(self, eurlex_source: EurlexSource) -> None:
        fixture = (FIXTURE_DIR / "32013L0036.xml").read_bytes()
        raw = RawDocument(
            source="eurlex",
            source_id="32013L0036",
            raw_url="https://eur-lex.europa.eu/legal-content/ES/TXT/XML/?uri=CELEX:32013L0036",
            content_type="xml",
            raw_bytes=fixture,
        )
        doc = eurlex_source.parse_to_canonical(raw)
        assert doc.type == "directive"


class TestChecksumStability:
    def test_checksum_stability(self, eurlex_source: EurlexSource) -> None:
        fixture = (FIXTURE_DIR / "32013R0575.xml").read_bytes()
        raw = RawDocument(
            source="eurlex",
            source_id="32013R0575",
            raw_url="",
            content_type="xml",
            raw_bytes=fixture,
        )
        doc1 = eurlex_source.parse_to_canonical(raw)
        doc2 = eurlex_source.parse_to_canonical(raw)
        assert doc1.checksum == doc2.checksum
        assert doc1.checksum != ""
