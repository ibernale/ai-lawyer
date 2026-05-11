"""Extract normative claims from legal text and associate them with [REF:n] citations."""

from __future__ import annotations

from dataclasses import dataclass

import regex
import structlog
from lex_agents_shared.types import CitationMapping

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns (regex module, not stdlib re)
# ---------------------------------------------------------------------------

_PATTERNS: list[regex.Pattern[str]] = [
    # 1. Article/section references
    regex.compile(
        r'\b(?:el|la|los|las)\s+art[íi]culo[s]?\s+\d+[a-z]?(?:\s*(?:bis|ter|quáter))?\b',
        regex.IGNORECASE | regex.UNICODE,
    ),
    # 2. Norm names
    regex.compile(
        r'\b(?:Reglamento|Directiva|Ley|Real\s+Decreto(?:-[Ll]ey)?|Circular|Reglamento\s+Delegado)\s+(?:\(UE\)\s+)?(?:n[oº°]?\s*\.?\s*)?\d[\d/]*\b',
        regex.IGNORECASE | regex.UNICODE,
    ),
    # 3. Legal obligations
    regex.compile(
        r'\b(?:establece|dispone|exige|proh[íi]be|permite|obliga(?:rá)?|impon(?:e|drá)|requiere|determina|prev[eé])\b',
        regex.IGNORECASE | regex.UNICODE,
    ),
    # 4. Jurisprudence
    regex.compile(
        r'\b(?:STS|SAP|STJUE|STC|STJCE)\s+(?:de\s+)?\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b',
        regex.IGNORECASE | regex.UNICODE,
    ),
    # 5. Regulatory bodies
    regex.compile(
        r'\b(?:BCE|BdE|Banco\s+de\s+España|Banco\s+Central\s+Europeo|EBA|ESMA|EIOPA|JUR|SRB)\b',
        regex.IGNORECASE | regex.UNICODE,
    ),
]

_REF_PATTERN: regex.Pattern[str] = regex.compile(r'\[REF:(\d+)\]')

_WINDOW_CHARS = 200


@dataclass
class Claim:
    text: str
    ref_index: int | None
    start_char: int
    end_char: int


class ClaimExtractor:
    """Extract normative claims from legal text."""

    def extract(self, text: str, citation_mapping: list[CitationMapping]) -> list[Claim]:
        """Find all normative claims and associate [REF:n] if present within 200 chars."""
        raw_claims: list[Claim] = []

        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                start = match.start()
                end = match.end()

                # Look for [REF:n] within 200 chars after match end
                window = text[end: end + _WINDOW_CHARS]
                ref_match = _REF_PATTERN.search(window)
                ref_index: int | None = None
                if ref_match:
                    ref_index = int(ref_match.group(1))

                raw_claims.append(Claim(
                    text=match.group(0),
                    ref_index=ref_index,
                    start_char=start,
                    end_char=end,
                ))

        # Deduplicate overlapping claims — keep the longer one
        claims = _deduplicate(raw_claims)
        claims.sort(key=lambda c: c.start_char)

        logger.debug(
            "claim_extractor.extracted",
            total=len(claims),
            with_ref=sum(1 for c in claims if c.ref_index is not None),
        )
        return claims


def _deduplicate(claims: list[Claim]) -> list[Claim]:
    """Remove overlapping claims, keeping the longest span."""
    if not claims:
        return []

    # Sort by start, then by length descending
    sorted_claims = sorted(claims, key=lambda c: (c.start_char, -(c.end_char - c.start_char)))
    result: list[Claim] = []

    for claim in sorted_claims:
        # Check if this claim overlaps with any already-kept claim
        overlaps = False
        for kept in result:
            if claim.start_char < kept.end_char and claim.end_char > kept.start_char:
                # Overlapping — keep the longer one
                if (claim.end_char - claim.start_char) > (kept.end_char - kept.start_char):
                    result.remove(kept)
                    result.append(claim)
                overlaps = True
                break
        if not overlaps:
            result.append(claim)

    return result
