from __future__ import annotations
import hashlib
import chardet
from lex_agents_documents.exceptions import ParseError
from lex_agents_documents.types import ParsedDocument

class TxtParser:
    def parse(self, raw_bytes: bytes, filename: str, doc_id: str) -> ParsedDocument:
        detection = chardet.detect(raw_bytes)
        encoding = detection.get("encoding") or "utf-8"
        try:
            text = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            try:
                text = raw_bytes.decode("latin-1")
            except Exception as e:
                raise ParseError(f"encoding_error: {e}") from e

        # Normalise to UTF-8
        text = text.encode("utf-8", errors="replace").decode("utf-8")

        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            mime_type="text/plain",
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            text=text,
            metadata={"detected_encoding": encoding},
        )
