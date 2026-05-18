"""Unit tests for new 11C.1 source implementations.

Tests use httpx mock transport to avoid real network calls.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import httpx
import pytest
from lex_agents_ingest.canonical import CanonicalDocument
from lex_agents_ingest.sources.bcb_brasil import BcbBrasilSource
from lex_agents_ingest.sources.bcbs_bis import BcbsBisSource
from lex_agents_ingest.sources.bcra import BcraSource
from lex_agents_ingest.sources.cnmc import CnmcSource
from lex_agents_ingest.sources.federal_register import FederalRegisterSource
from lex_agents_ingest.sources.sepblac import SepblacSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_transport(routes: dict[str, tuple[int, bytes, str]]) -> httpx.MockTransport:
    """Build a simple httpx MockTransport from a URL→(status, body, content_type) dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, (status, body, ct) in routes.items():
            if url.startswith(prefix) or url == prefix:
                return httpx.Response(status, content=body, headers={"content-type": ct})
        return httpx.Response(404, content=b"Not found")

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# CNMC
# ---------------------------------------------------------------------------

_CNMC_HTML = (
    "<html><body>"
    "<h1>Resolución CNMC/DS/013/23</h1>"
    "<p>Fecha: 15/03/2023</p>"
    "<a href=\"/expediente/DS-013-23\">Ver expediente</a>"
    "<article>Contenido de la resolución.</article>"
    "</body></html>"
).encode()

_CNMC_LISTING = (
    "<html><body>"
    "<a href=\"/expediente/DS-013-23\">Resolución DS-013-23</a>"
    "<a href=\"/expediente/DS-014-23\">Resolución DS-014-23</a>"
    "</body></html>"
).encode()


def _make_cnmc_client() -> httpx.AsyncClient:
    routes = {
        "https://www.cnmc.es/api/v1/resoluciones": (200, b"[]", "application/json"),
        "https://www.cnmc.es/expedientes": (200, _CNMC_LISTING, "text/html"),
        "https://www.cnmc.es/expediente/DS-013-23": (200, _CNMC_HTML, "text/html"),
    }
    return httpx.AsyncClient(transport=_mock_transport(routes))


@pytest.mark.anyio
async def test_cnmc_list_documents_html_fallback():
    src = CnmcSource(http_client=_make_cnmc_client())
    ids = await src.list_documents()
    assert len(ids) >= 2
    assert any("DS-013-23" in i for i in ids)


@pytest.mark.anyio
async def test_cnmc_parse_to_canonical():
    from lex_agents_ingest.canonical import RawDocument

    raw = RawDocument(
        source="cnmc",
        source_id="DS-013-23",
        raw_url="https://www.cnmc.es/expediente/DS-013-23",
        content_type="html",
        raw_bytes=_CNMC_HTML,
        fetched_at=datetime.utcnow(),
    )
    src = CnmcSource()
    doc = src.parse_to_canonical(raw)
    assert isinstance(doc, CanonicalDocument)
    assert doc.jurisdiction == "ES"
    assert doc.source == "cnmc"
    assert "CNMC" in doc.title or "Resolución" in doc.title
    assert doc.publication_date == date(2023, 3, 15)


# ---------------------------------------------------------------------------
# SEPBLAC
# ---------------------------------------------------------------------------

_SEPBLAC_HTML = (
    b"<html><body>"
    b"<h1>Guia de Referencia: DDC en Entidades Financieras</h1>"
    b"<p>25/01/2024</p>"
    b"<p>Contenido de la guia de referencia SEPBLAC.</p>"
    b"</body></html>"
)

_SEPBLAC_LISTING = (
    b"<html><body>"
    b"<a href=\"/es/sujetos-obligados/guia-ddc-2024\">Guia DDC 2024</a>"
    b"<a href=\"/files/informe-2023.pdf\">Informe anual 2023 (PDF)</a>"
    b"</body></html>"
)


def _make_sepblac_client() -> httpx.AsyncClient:
    routes = {
        "https://www.sepblac.es/es/sujetos-obligados/guias-y-comunicados": (200, _SEPBLAC_LISTING, "text/html"),
        "https://www.sepblac.es/es/sujetos-obligados/guia-ddc-2024": (200, _SEPBLAC_HTML, "text/html"),
    }
    return httpx.AsyncClient(transport=_mock_transport(routes))


def test_sepblac_parse_html_doc():
    from lex_agents_ingest.canonical import RawDocument

    raw = RawDocument(
        source="sepblac",
        source_id="https://www.sepblac.es/es/guia-ddc",
        raw_url="https://www.sepblac.es/es/guia-ddc",
        content_type="html",
        raw_bytes=_SEPBLAC_HTML,
        fetched_at=datetime.utcnow(),
    )
    src = SepblacSource()
    doc = src.parse_to_canonical(raw)
    assert doc.jurisdiction == "ES"
    assert doc.domain == "aml_compliance"
    assert doc.type == "guia"
    assert doc.publication_date == date(2024, 1, 25)


def test_sepblac_parse_pdf_stub():
    from lex_agents_ingest.canonical import RawDocument

    raw = RawDocument(
        source="sepblac",
        source_id="https://www.sepblac.es/files/informe-2023.pdf",
        raw_url="https://www.sepblac.es/files/informe-2023.pdf",
        content_type="pdf",
        raw_bytes=b"%PDF-stub",
        fetched_at=datetime.utcnow(),
    )
    src = SepblacSource()
    doc = src.parse_to_canonical(raw)
    assert doc.domain == "aml_compliance"
    assert doc.full_text == ""  # populated by Docling later


# ---------------------------------------------------------------------------
# BCBS/BIS
# ---------------------------------------------------------------------------

_BIS_HTML = (
    b"<html><body>"
    b"<h1>Basel III: Finalising post-crisis reforms (BCBS d424)</h1>"
    b"<p>7 December 2017</p>"
    b"<article>Full text of the standard...</article>"
    b"</body></html>"
)

_BIS_LISTING = (
    b"<html><body>"
    b"<a href=\"/publ/d424.htm\">Basel III d424</a>"
    b"<a href=\"/publ/d558.pdf\">Disclosure d558</a>"
    b"</body></html>"
)


def _make_bis_client() -> httpx.AsyncClient:
    routes = {
        "https://www.bis.org/bcbs/publications.htm": (200, _BIS_LISTING, "text/html"),
        "https://www.bis.org/publ/d424.htm": (200, _BIS_HTML, "text/html"),
    }
    return httpx.AsyncClient(transport=_mock_transport(routes))


@pytest.mark.anyio
async def test_bcbs_bis_list_documents():
    src = BcbsBisSource(http_client=_make_bis_client())
    ids = await src.list_documents()
    assert any("d424" in i for i in ids)
    assert any("d558" in i for i in ids)


def test_bcbs_bis_parse_standard():
    from lex_agents_ingest.canonical import RawDocument

    raw = RawDocument(
        source="bcbs_bis",
        source_id="https://www.bis.org/publ/d424.htm",
        raw_url="https://www.bis.org/publ/d424.htm",
        content_type="html",
        raw_bytes=_BIS_HTML,
        fetched_at=datetime.utcnow(),
    )
    src = BcbsBisSource()
    doc = src.parse_to_canonical(raw)
    assert doc.jurisdiction == "GLOBAL"
    assert doc.domain == "regulatorio_bancario_ue_es"
    assert "Basel III" in doc.title
    assert doc.publication_date == date(2017, 12, 7)


# ---------------------------------------------------------------------------
# Federal Register
# ---------------------------------------------------------------------------

_FR_DOC = json.dumps({
    "document_number": "2024-05678",
    "title": "Bank Secrecy Act Anti-Money Laundering Regulations",
    "abstract": "FinCEN proposes to amend BSA regulations...",
    "publication_date": "2024-03-15",
    "type": "PRORULE",
    "agencies": [{"name": "Financial Crimes Enforcement Network", "slug": "financial-crimes-enforcement-network"}],
    "html_url": "https://www.federalregister.gov/documents/2024/03/15/2024-05678/bank-secrecy-act",
}).encode()

_FR_LISTING = json.dumps({"results": [{"document_number": "2024-05678"}]}).encode()


def _make_fr_client() -> httpx.AsyncClient:
    routes = {
        "https://www.federalregister.gov/api/v1/documents.json": (200, _FR_LISTING, "application/json"),
        "https://www.federalregister.gov/api/v1/documents/2024-05678.json": (200, _FR_DOC, "application/json"),
    }
    return httpx.AsyncClient(transport=_mock_transport(routes))


@pytest.mark.anyio
async def test_federal_register_list():
    src = FederalRegisterSource(http_client=_make_fr_client())
    ids = await src.list_documents()
    assert "2024-05678" in ids


@pytest.mark.anyio
async def test_federal_register_fetch_and_parse():
    src = FederalRegisterSource(http_client=_make_fr_client())
    raw = await src.fetch("2024-05678")
    doc = src.parse_to_canonical(raw)
    assert doc.jurisdiction == "US"
    assert doc.type == "proposed_rule"
    assert doc.domain == "aml_compliance"
    assert doc.publication_date == date(2024, 3, 15)
    assert "FinCEN" in doc.title or "Bank Secrecy" in doc.title


# ---------------------------------------------------------------------------
# BCB Brasil
# ---------------------------------------------------------------------------

_BCB_HTML = (
    b"<html><body>"
    b"<h1>Circular 4.000 -- Requisitos de capital regulatorio</h1>"
    b"<p>Data: 10/06/2023</p>"
    b"<p>O Banco Central do Brasil determina...</p>"
    b"</body></html>"
)

_BCB_LISTING = (
    b"<html><body>"
    b"<a href=\"/normativos/circular/4000\">Circular 4000</a>"
    b"<a href=\"/normativos/resolucao/cmc/2023-001\">Resolucao CMC 2023-001</a>"
    b"</body></html>"
)


def _make_bcb_client() -> httpx.AsyncClient:
    routes = {
        "https://www.bcb.gov.br/estabilidadefinanceira/normativos": (200, _BCB_LISTING, "text/html"),
        "https://www.bcb.gov.br/normativos/circular/4000": (200, _BCB_HTML, "text/html"),
    }
    return httpx.AsyncClient(transport=_mock_transport(routes))


@pytest.mark.anyio
async def test_bcb_brasil_list():
    src = BcbBrasilSource(http_client=_make_bcb_client())
    ids = await src.list_documents()
    assert len(ids) >= 1
    assert any("circular" in i.lower() for i in ids)


def test_bcb_brasil_parse():
    from lex_agents_ingest.canonical import RawDocument

    raw = RawDocument(
        source="bcb_brasil",
        source_id="https://www.bcb.gov.br/normativos/circular/4000",
        raw_url="https://www.bcb.gov.br/normativos/circular/4000",
        content_type="html",
        raw_bytes=_BCB_HTML,
        fetched_at=datetime.utcnow(),
    )
    src = BcbBrasilSource()
    doc = src.parse_to_canonical(raw)
    assert doc.jurisdiction == "BR"
    assert doc.type == "circular"
    assert doc.publication_date == date(2023, 6, 10)


# ---------------------------------------------------------------------------
# BCRA
# ---------------------------------------------------------------------------

_BCRA_HTML = (
    b"<html><body>"
    b"<title>Com. A 7650 - BCRA</title>"
    b"<h1>Comunicacion A 7650</h1>"
    b"<p>15/09/2023</p>"
    b"<p>El Banco Central de la Republica Argentina...</p>"
    b"</body></html>"
)

_BCRA_LISTING = (
    b"<html><body>"
    b"<a href=\"/SistemasFinancieros/norma-7650.asp\">Com. A 7650</a>"
    b"<a href=\"/SistemasFinancieros/circular-runor-1.pdf\">RUNOR 1 (PDF)</a>"
    b"</body></html>"
)


def _make_bcra_client() -> httpx.AsyncClient:
    routes = {
        "https://www.bcra.gob.ar/SistemasFinancieros/sf010000.asp": (200, _BCRA_LISTING, "text/html"),
        "https://www.bcra.gob.ar/SistemasFinancieros/norma-7650.asp": (200, _BCRA_HTML, "text/html"),
    }
    return httpx.AsyncClient(transport=_mock_transport(routes))


@pytest.mark.anyio
async def test_bcra_list():
    src = BcraSource(http_client=_make_bcra_client())
    ids = await src.list_documents()
    assert len(ids) >= 1


def test_bcra_parse():
    from lex_agents_ingest.canonical import RawDocument

    raw = RawDocument(
        source="bcra",
        source_id="https://www.bcra.gob.ar/SistemasFinancieros/norma-7650.asp",
        raw_url="https://www.bcra.gob.ar/SistemasFinancieros/norma-7650.asp",
        content_type="html",
        raw_bytes=_BCRA_HTML,
        fetched_at=datetime.utcnow(),
    )
    src = BcraSource()
    doc = src.parse_to_canonical(raw)
    assert doc.jurisdiction == "AR"
    assert doc.type == "comunicacion"
    assert doc.publication_date == date(2023, 9, 15)
