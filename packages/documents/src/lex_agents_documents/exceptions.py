"""Document pipeline exceptions."""

from __future__ import annotations


class ParseError(Exception):
    """Raised when a document cannot be parsed (corrupt, password-protected, image-only)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Parse error: {reason}")


class UnsupportedFormatError(Exception):
    """Raised when the detected MIME type has no registered parser."""

    def __init__(self, mime_type: str) -> None:
        self.mime_type = mime_type
        super().__init__(f"Unsupported format: {mime_type}")


class DocumentTooLargeError(Exception):
    """Raised when a document exceeds hard limits (50 MB or 200 PDF pages)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Document too large: {reason}")
