"""PII detection and redaction for Spanish/EU personal data categories."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _PiiPattern:
    label: str
    pattern: re.Pattern[str]


_PATTERNS: list[_PiiPattern] = [
    # Spanish DNI: 8 digits + letter (case-insensitive)
    _PiiPattern("DNI", re.compile(r"\b[0-9]{8}[A-HJ-NP-TV-Za-hj-np-tv-z]\b")),
    # Spanish NIE: X/Y/Z + 7 digits + letter
    _PiiPattern("NIE", re.compile(r"\b[XYZxyz][0-9]{7}[A-HJ-NP-TV-Za-hj-np-tv-z]\b")),
    # Spanish NIF for companies: letter + 8 chars (digit or letter)
    _PiiPattern("NIF", re.compile(r"\b[ABCDEFGHJNPQRSUVWabcdefghjnpqrsuvw][0-9]{7}[0-9A-Ja-j]\b")),
    # IBAN (ES): ES + 22 digits — handle optional spaces
    _PiiPattern("IBAN", re.compile(r"\bES\s*[0-9]{2}\s*[0-9]{4}\s*[0-9]{4}\s*[0-9]{4}\s*[0-9]{4}\s*[0-9]{4}\b")),
    # Spanish bank account (20-digit BBAN without IBAN prefix)
    _PiiPattern("ACCOUNT", re.compile(r"\b[0-9]{4}\s?[0-9]{4}\s?[0-9]{2}\s?[0-9]{10}\b")),
    # Credit card (16 digits, optionally grouped with spaces/dashes — Luhn not checked here)
    _PiiPattern("CARD", re.compile(r"\b(?:[0-9]{4}[-\s]?){3}[0-9]{4}\b")),
    # Email
    _PiiPattern("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Spanish phone: +34 or leading 6/7/9 followed by 8 digits
    _PiiPattern("PHONE", re.compile(r"(?:\+34\s?|(?<!\d))(?:6|7|9)[0-9]{8}\b")),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def redact_pii(text: str) -> str:
    """Replace all detected PII tokens with [PII:TYPE] markers.

    Patterns are applied in order; earlier matches prevent double-redaction.
    Designed to be used as a structlog processor value transformer.
    """
    for entry in _PATTERNS:
        text = entry.pattern.sub(f"[PII:{entry.label}]", text)
    return text


def contains_pii(text: str) -> bool:
    """Return True if any PII pattern matches anywhere in *text*."""
    return any(entry.pattern.search(text) is not None for entry in _PATTERNS)
