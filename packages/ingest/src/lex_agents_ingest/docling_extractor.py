"""DoclingExtractor — advanced document parsing for PDF and DOCX.

Uses Docling (>=2.0.0) for high-fidelity extraction of:
- Structured text with layout awareness (tables, headers, footnotes)
- Markdown export suitable for chunking
- Page count from PDF metadata

If Docling is not installed, falls back gracefully to pdfminer (PDF) and
python-docx (DOCX) for backwards compatibility.

Usage::

    extractor = DoclingExtractor()
    text, page_count = extractor.extract(data, mime_type, filename)

The returned *text* is Markdown-formatted when Docling handles the conversion,
plain text otherwise.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DOCLING_AVAILABLE: bool | None = None  # lazy-checked on first call


def _check_docling() -> bool:
    global _DOCLING_AVAILABLE
    if _DOCLING_AVAILABLE is None:
        try:
            import docling  # noqa: F401
            _DOCLING_AVAILABLE = True
            logger.debug("docling_extractor_backend", backend="docling")
        except ImportError:
            _DOCLING_AVAILABLE = False
            logger.warning(
                "docling_not_installed",
                message="Install docling>=2.0.0 for advanced document parsing. "
                        "Falling back to pdfminer/python-docx.",
            )
    return _DOCLING_AVAILABLE


def _extract_with_docling(data: bytes, suffix: str) -> tuple[str, int | None]:
    """Extract text using Docling. Writes bytes to a temp file.

    Returns (markdown_text, page_count).
    page_count is None for DOCX (Docling does not report it).
    """
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        result = converter.convert(str(tmp_path))
        doc = result.document
        text = doc.export_to_markdown()

        # Attempt to get page count from the document metadata
        page_count: int | None = None
        try:
            pages = getattr(doc, "pages", None)
            if pages:
                page_count = len(pages)
        except Exception:
            pass

        logger.info(
            "docling_extraction_ok",
            suffix=suffix,
            chars=len(text),
            pages=page_count,
        )
        return text, page_count
    finally:
        tmp_path.unlink(missing_ok=True)


def _extract_pdf_fallback(data: bytes) -> tuple[str, int]:
    """Fallback PDF extraction via pdfminer."""
    from pdfminer.high_level import extract_text as _pdf_text
    from pdfminer.pdfpage import PDFPage

    text = _pdf_text(io.BytesIO(data)) or ""
    page_count = sum(
        1 for _ in PDFPage.get_pages(io.BytesIO(data), check_extractable=False)
    )
    logger.debug("docling_fallback_pdf", chars=len(text), pages=page_count)
    return text, page_count


def _extract_docx_fallback(data: bytes) -> tuple[str, None]:
    """Fallback DOCX extraction via python-docx."""
    import docx

    doc = docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    logger.debug("docling_fallback_docx", chars=len(text))
    return text, None


class DoclingExtractor:
    """Unified document text extractor.

    Prefers Docling (Markdown output, table-aware, layout-preserving).
    Falls back to pdfminer / python-docx when Docling is unavailable.
    """

    def extract(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
    ) -> tuple[str, int | None]:
        """Extract text from *data*.

        Args:
            data:      Raw document bytes.
            mime_type: MIME type string (e.g. ``"application/pdf"``).
            filename:  Original filename used to infer format by extension.

        Returns:
            A ``(text, page_count)`` tuple.
            *text* is Markdown when Docling is used, plain text otherwise.
            *page_count* is ``None`` for DOCX.

        Raises:
            ValueError: If the format is unsupported and no fallback is available.
        """
        fn_lower = filename.lower()
        is_pdf = mime_type == "application/pdf" or fn_lower.endswith(".pdf")
        is_docx = mime_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ) or fn_lower.endswith((".docx", ".doc"))

        if not is_pdf and not is_docx:
            # Plain text or unknown — decode directly
            try:
                return data.decode("utf-8", errors="replace"), None
            except Exception as exc:
                raise ValueError(f"Cannot decode document: {exc}") from exc

        suffix = ".pdf" if is_pdf else ".docx"

        if _check_docling():
            try:
                return _extract_with_docling(data, suffix)
            except Exception:
                logger.exception("docling_extraction_failed", filename=filename)
                # Fall through to legacy fallbacks

        # Legacy fallbacks
        if is_pdf:
            return _extract_pdf_fallback(data)
        return _extract_docx_fallback(data)


# Module-level singleton for use in the documents router
_extractor: DoclingExtractor | None = None


def get_extractor() -> DoclingExtractor:
    """Return the module-level DoclingExtractor singleton."""
    global _extractor
    if _extractor is None:
        _extractor = DoclingExtractor()
    return _extractor
