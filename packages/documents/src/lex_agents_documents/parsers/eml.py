from __future__ import annotations
import hashlib
import mailparser
from lex_agents_documents.exceptions import ParseError
from lex_agents_documents.types import ParsedDocument

class EmlParser:
    def parse(self, raw_bytes: bytes, filename: str, doc_id: str) -> ParsedDocument:
        try:
            mail = mailparser.parse_from_bytes(raw_bytes)
        except Exception as e:
            raise ParseError(f"corrupt_eml: {e}") from e

        parts: list[str] = []
        if mail.body:
            parts.append(mail.body)

        attachment_names: list[str] = []
        for att in mail.attachments:
            if att.get("mail_content_type", "").startswith("text/plain"):
                payload = att.get("payload", "")
                if payload:
                    parts.append(f"\n--- Attachment: {att.get('filename', 'unnamed')} ---\n{payload}")
            else:
                attachment_names.append(att.get("filename", "unnamed"))

        text = "\n".join(parts)
        metadata: dict[str, str] = {}
        if attachment_names:
            metadata["attachments"] = ", ".join(attachment_names)
        if mail.subject:
            metadata["subject"] = mail.subject

        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            mime_type="message/rfc822",
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            text=text,
            metadata=metadata,
        )
