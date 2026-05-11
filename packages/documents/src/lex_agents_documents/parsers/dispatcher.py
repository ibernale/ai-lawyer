from __future__ import annotations
import os
from pathlib import Path
from lex_agents_documents.exceptions import DocumentTooLargeError, UnsupportedFormatError
from lex_agents_documents.parsers.pdf import PDFParser
from lex_agents_documents.parsers.docx import DocxParser
from lex_agents_documents.parsers.txt import TxtParser
from lex_agents_documents.parsers.eml import EmlParser
from lex_agents_documents.segmentation import LegalSegmenter
from lex_agents_documents.types import ParsedDocument

_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

_EXT_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".eml": "message/rfc822",
}

_PARSERS = {
    "application/pdf": PDFParser,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser,
    "text/plain": TxtParser,
    "message/rfc822": EmlParser,
}

def _detect_mime(raw_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _EXT_MIME:
        return _EXT_MIME[ext]
    # Try python-magic if available
    try:
        import magic
        return magic.from_buffer(raw_bytes[:2048], mime=True)
    except ImportError:
        pass
    return "application/octet-stream"

def detect_and_parse(raw_bytes: bytes, filename: str, doc_id: str) -> ParsedDocument:
    if len(raw_bytes) > _MAX_BYTES:
        raise DocumentTooLargeError(f"exceeds 50 MB ({len(raw_bytes) / 1024 / 1024:.1f} MB)")

    mime = _detect_mime(raw_bytes, filename)
    parser_cls = _PARSERS.get(mime)
    if parser_cls is None:
        raise UnsupportedFormatError(mime)

    parsed = parser_cls().parse(raw_bytes, filename, doc_id)
    LegalSegmenter().segment(parsed)
    return parsed
