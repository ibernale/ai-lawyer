"""Unit tests for DoclingExtractor (Fase 11C.3).

Tests use mocking to avoid requiring Docling to be installed in the test
environment. Both the Docling path and the fallback path are covered.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lex_agents_ingest.docling_extractor import DoclingExtractor, get_extractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAIN_TEXT = b"Este es un documento de prueba. Contiene texto plano."

_PDF_STUB = b"%PDF-1.4 stub"
_DOCX_STUB = b"PK\x03\x04stub"  # ZIP magic bytes (DOCX is a ZIP)


# ---------------------------------------------------------------------------
# Plain text extraction (no Docling needed)
# ---------------------------------------------------------------------------


def test_extract_plain_text():
    extractor = DoclingExtractor()
    text, page_count = extractor.extract(_PLAIN_TEXT, "text/plain", "doc.txt")
    assert "Este es un documento" in text
    assert page_count is None


def test_extract_unknown_mime_defaults_to_utf8():
    extractor = DoclingExtractor()
    data = "Contenido desconocido.".encode("utf-8")
    text, page_count = extractor.extract(data, "application/octet-stream", "file.xyz")
    assert "Contenido desconocido" in text
    assert page_count is None


# ---------------------------------------------------------------------------
# Docling path (mocked)
# ---------------------------------------------------------------------------


def _make_docling_mock(markdown: str, n_pages: int | None = 3) -> MagicMock:
    """Build a mock DocumentConverter that returns *markdown* text."""
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = markdown
    if n_pages is not None:
        mock_doc.pages = [MagicMock()] * n_pages
    else:
        mock_doc.pages = None

    mock_result = MagicMock()
    mock_result.document = mock_doc

    mock_converter = MagicMock()
    mock_converter.return_value = mock_converter
    mock_converter.convert.return_value = mock_result
    return mock_converter


def test_extract_pdf_with_docling():
    markdown = "# Basel III\n\nRequisitos de capital..."
    mock_converter = _make_docling_mock(markdown, n_pages=5)

    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", True), \
         patch("lex_agents_ingest.docling_extractor._extract_with_docling",
               return_value=(markdown, 5)) as mock_extract:
        extractor = DoclingExtractor()
        text, pages = extractor.extract(_PDF_STUB, "application/pdf", "basell3.pdf")

    mock_extract.assert_called_once_with(_PDF_STUB, ".pdf")
    assert text == markdown
    assert pages == 5


def test_extract_docx_with_docling():
    markdown = "## Contrato\n\nCláusula 1..."
    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", True), \
         patch("lex_agents_ingest.docling_extractor._extract_with_docling",
               return_value=(markdown, None)) as mock_extract:
        extractor = DoclingExtractor()
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        text, pages = extractor.extract(_DOCX_STUB, mime, "contrato.docx")

    mock_extract.assert_called_once_with(_DOCX_STUB, ".docx")
    assert text == markdown
    assert pages is None


def test_docling_exception_falls_back_to_pdfminer():
    """When Docling raises an exception, extractor falls back to pdfminer."""
    fallback_text = "Texto extraído por pdfminer"

    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", True), \
         patch("lex_agents_ingest.docling_extractor._extract_with_docling",
               side_effect=RuntimeError("docling internal error")), \
         patch("lex_agents_ingest.docling_extractor._extract_pdf_fallback",
               return_value=(fallback_text, 2)) as mock_fallback:
        extractor = DoclingExtractor()
        text, pages = extractor.extract(_PDF_STUB, "application/pdf", "doc.pdf")

    mock_fallback.assert_called_once_with(_PDF_STUB)
    assert text == fallback_text
    assert pages == 2


# ---------------------------------------------------------------------------
# Fallback paths (Docling not installed)
# ---------------------------------------------------------------------------


def test_pdf_fallback_when_docling_unavailable():
    fallback_text = "Texto PDF extraído por pdfminer"
    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", False), \
         patch("lex_agents_ingest.docling_extractor._extract_pdf_fallback",
               return_value=(fallback_text, 4)) as mock_fb:
        extractor = DoclingExtractor()
        text, pages = extractor.extract(_PDF_STUB, "application/pdf", "test.pdf")

    mock_fb.assert_called_once()
    assert text == fallback_text
    assert pages == 4


def test_docx_fallback_when_docling_unavailable():
    fallback_text = "Texto DOCX extraído por python-docx"
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", False), \
         patch("lex_agents_ingest.docling_extractor._extract_docx_fallback",
               return_value=(fallback_text, None)) as mock_fb:
        extractor = DoclingExtractor()
        text, pages = extractor.extract(_DOCX_STUB, mime, "test.docx")

    mock_fb.assert_called_once()
    assert text == fallback_text
    assert pages is None


# ---------------------------------------------------------------------------
# Extension-based detection
# ---------------------------------------------------------------------------


def test_pdf_detected_by_extension():
    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", False), \
         patch("lex_agents_ingest.docling_extractor._extract_pdf_fallback",
               return_value=("text", 1)) as mock_fb:
        DoclingExtractor().extract(_PDF_STUB, "application/octet-stream", "report.PDF")
    mock_fb.assert_called_once()


def test_docx_detected_by_extension():
    with patch("lex_agents_ingest.docling_extractor._DOCLING_AVAILABLE", False), \
         patch("lex_agents_ingest.docling_extractor._extract_docx_fallback",
               return_value=("text", None)) as mock_fb:
        DoclingExtractor().extract(_DOCX_STUB, "application/octet-stream", "contract.docx")
    mock_fb.assert_called_once()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_extractor_returns_singleton():
    # Reset singleton for clean test
    import lex_agents_ingest.docling_extractor as mod
    mod._extractor = None

    e1 = get_extractor()
    e2 = get_extractor()
    assert e1 is e2
    assert isinstance(e1, DoclingExtractor)
