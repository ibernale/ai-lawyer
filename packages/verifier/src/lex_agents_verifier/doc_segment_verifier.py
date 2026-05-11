"""Verifier for [DOC:s] segment citations in document-agent answers."""

from __future__ import annotations

import re

from lex_agents_shared.types import ClaimVerification

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+.*instructions", re.IGNORECASE),
    re.compile(r"^system:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"<\|"),
    re.compile(r"\[INST\]"),
]

_STOPWORDS = {
    "de", "la", "el", "en", "que", "y", "los", "las", "del", "al", "por", "con", "se",
    "una", "un", "es", "son", "para", "como", "más", "pero", "sus", "le", "ya", "o",
    "fue", "este", "entre", "cuando", "muy", "sin", "sobre", "ser", "tiene", "también",
    "hasta", "hay", "donde", "quien", "desde", "todo", "nos", "durante", "todos", "uno",
    "les", "ni", "contra", "otros", "ese", "eso", "ante", "ellos", "e", "esto", "mí",
    "antes", "algunos", "qué", "unos", "yo", "otro", "otras", "otra", "él", "tanto",
    "esa", "estos", "mucho", "quienes", "nada", "muchos", "cual", "poco", "ella",
}

_JACCARD_THRESHOLD = 0.70


def _tokenize(text: str) -> set[str]:
    tokens = set(re.split(r"\W+", text.lower()))
    return tokens - _STOPWORDS - {""}


class DocSegmentVerifier:
    """Heuristic verifier for [DOC:s] citations against document segments."""

    def verify(
        self,
        claim_text: str,
        segment_text: str,
        segment_index: int,
    ) -> ClaimVerification:
        """Verify that a claim is supported by the referenced document segment.

        Args:
            claim_text: The surrounding text that makes the claim.
            segment_text: The text of the referenced document segment.
            segment_index: The 1-based [DOC:s] index being verified.

        Returns:
            ClaimVerification with verdict PASSED, UNCERTAIN, or FAILED.
        """
        # Check 1: index bounds
        if segment_index < 1:
            return ClaimVerification(
                ref_index=segment_index,
                verdict="FAILED",
                method="heuristic",
                confidence=0.0,
                failure_reason="REJECTED_INVALID_INDEX",
            )

        # Check 2: empty segment
        if not segment_text.strip():
            return ClaimVerification(
                ref_index=segment_index,
                verdict="FAILED",
                method="heuristic",
                confidence=0.0,
                failure_reason="REJECTED_EMPTY_SEGMENT",
            )

        # Check 3: prompt injection
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(segment_text):
                return ClaimVerification(
                    ref_index=segment_index,
                    verdict="FAILED",
                    method="heuristic",
                    confidence=0.0,
                    failure_reason="REJECTED_INJECTION_ATTEMPT",
                )

        # Check 4: Jaccard similarity
        claim_tokens = _tokenize(claim_text)
        seg_tokens = _tokenize(segment_text)
        if not claim_tokens or not seg_tokens:
            jaccard = 0.0
        else:
            jaccard = len(claim_tokens & seg_tokens) / len(claim_tokens | seg_tokens)

        if jaccard < _JACCARD_THRESHOLD:
            return ClaimVerification(
                ref_index=segment_index,
                verdict="UNCERTAIN",
                method="heuristic",
                confidence=jaccard,
                failure_reason=f"LOW_SIMILARITY ({jaccard:.2f})",
            )

        return ClaimVerification(
            ref_index=segment_index,
            verdict="PASSED",
            method="heuristic",
            confidence=jaccard,
            failure_reason=None,
        )
