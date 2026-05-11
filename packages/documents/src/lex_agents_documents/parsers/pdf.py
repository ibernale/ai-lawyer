from __future__ import annotations
import hashlib, io
import fitz  # PyMuPDF
import pymupdf4llm
from lex_agents_documents.exceptions import DocumentTooLargeError, ParseError
from lex_agents_documents.types import ParsedDocument

_MAX_PAGES = 200

class PDFParser:
    def parse(self, raw_bytes: bytes, filename: str, doc_id: str) -> ParsedDocument:
        try:
            fitz_doc = fitz.open(stream=raw_bytes, filetype="pdf")
        except Exception as e:
            raise ParseError(f"password_protected") from e

        if fitz_doc.needs_pass:
            raise ParseError("password_protected")
        if len(fitz_doc) > _MAX_PAGES:
            raise DocumentTooLargeError(f"exceeds 200 pages ({len(fitz_doc)})")

        text = pymupdf4llm.to_markdown(fitz_doc)
        if not text.strip():
            raise ParseError("image_only_pdf")

        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            mime_type="application/pdf",
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            page_count=len(fitz_doc),
            text=text,
            metadata={"pages": str(len(fitz_doc))},
        )
