"""Heuristic claim verifier — entity matching + trigram overlap."""

from __future__ import annotations

import regex
import structlog
from lex_agents_shared.types import ClaimVerification

from .claim_extractor import Claim

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Entity extraction patterns
# ---------------------------------------------------------------------------

_ARTICLE_NUMBER_PATTERN = regex.compile(
    r'(?:art[íi]culo[s]?|art\.?)\s*(\d+[a-z]?(?:\s*(?:bis|ter))?)',
    regex.IGNORECASE | regex.UNICODE,
)
_PERCENTAGE_PATTERN = regex.compile(r'\d+[,.]?\d*\s*%', regex.UNICODE)
_YEAR_PATTERN = regex.compile(r'\b(?:19|20)\d{2}\b', regex.UNICODE)
_NORM_ID_PATTERN = regex.compile(r'\b\d+/\d+(?:/[A-Z]{2,3})?\b', regex.UNICODE)


class HeuristicVerifier:
    """Verify claims using entity matching and trigram overlap."""

    def verify(self, claim: Claim, chunk_text: str) -> ClaimVerification:
        """Return a ClaimVerification for the given claim against chunk_text."""
        entity_match = self._entity_match(claim.text, chunk_text)
        overlap = self._phrase_overlap(claim.text, chunk_text)

        # Verdict logic
        if entity_match and overlap >= 0.2:
            verdict = "PASSED"
        elif entity_match and len(claim.text) < 50:
            verdict = "PASSED"
        elif entity_match or overlap >= 0.3:
            verdict = "UNCERTAIN"
        else:
            verdict = "FAILED"

        confidence_map = {"PASSED": 0.9, "UNCERTAIN": 0.5, "FAILED": 0.1}
        confidence = confidence_map[verdict]

        logger.debug(
            "heuristic_verifier.result",
            verdict=verdict,
            entity_match=entity_match,
            overlap=round(overlap, 3),
            claim_len=len(claim.text),
        )

        return ClaimVerification(
            ref_index=claim.ref_index or 0,
            verdict=verdict,  # type: ignore[arg-type]
            method="heuristic",
            confidence=confidence,
            failure_reason=None if verdict == "PASSED" else f"entity_match={entity_match}, overlap={overlap:.3f}",
        )

    # ------------------------------------------------------------------
    # Entity matching
    # ------------------------------------------------------------------

    def _entity_match(self, claim_text: str, chunk_text: str) -> bool:
        """Return True if any extracted entity from claim appears in chunk."""
        chunk_lower = chunk_text.lower().replace(" ", "")
        entities: list[str] = []

        # Article numbers
        for m in _ARTICLE_NUMBER_PATTERN.finditer(claim_text):
            entities.append(m.group(1).strip())

        # Percentages
        for m in _PERCENTAGE_PATTERN.finditer(claim_text):
            entities.append(m.group(0).strip())

        # Years
        for m in _YEAR_PATTERN.finditer(claim_text):
            entities.append(m.group(0))

        # Norm identifiers (e.g. 575/2013, 2013/36/UE)
        for m in _NORM_ID_PATTERN.finditer(claim_text):
            entities.append(m.group(0))

        if not entities:
            return False

        for entity in entities:
            normalized = entity.lower().replace(" ", "")
            if normalized in chunk_lower:
                return True

        return False

    # ------------------------------------------------------------------
    # Trigram overlap
    # ------------------------------------------------------------------

    def _trigrams(self, text: str) -> set[str]:
        words = text.lower().split()
        if len(words) < 3:
            return set()
        return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}

    def _phrase_overlap(self, claim_text: str, chunk_text: str) -> float:
        claim_tris = self._trigrams(claim_text)
        chunk_tris = self._trigrams(chunk_text)
        intersection = claim_tris & chunk_tris
        return len(intersection) / max(len(claim_tris), 1)
