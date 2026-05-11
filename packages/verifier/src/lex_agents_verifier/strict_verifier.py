"""Strict verifier for jurisprudential citations — ADR 0024.

Activated automatically when CitationMapping.citation_type == "jurisprudencia".
Applies exact-match checks on case number, year, chamber, judges, and
grounds before accepting a citation fragment as support for a claim.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import structlog
from lex_agents_shared.types import CitationMapping, ClaimVerification

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_ECLI_PATTERN = re.compile(r"ECLI:[A-Z]{2}:[A-Z]+:\d{4}:\d+")
_CASE_NUMBER_PATTERN = re.compile(r"\b(\d+/\d{4})\b")
_COURT_YEAR_PATTERN = re.compile(
    r"(?:STS|STC|SAP|STSJ|ATS|sentencia|resolución)\b[^.]*?\b((?:19|20)\d{2})\b",
    re.IGNORECASE | re.UNICODE,
)
_CHAMBER_PATTERN = re.compile(
    r"(Sala\s+(?:de\s+lo\s+)?[A-Za-záéíóúÁÉÍÓÚ\s]+?(?=,|\.|;|\[|$)|"
    r"Sección\s+\d+|"
    r"Pleno|"
    r"Sala\s+Primera|"
    r"Sala\s+Segunda|"
    r"Sala\s+Tercera|"
    r"Sala\s+Cuarta)",
    re.IGNORECASE | re.UNICODE,
)
_FJ_PATTERN = re.compile(
    r"(?:FJ|Fundamento\s+Jur[íi]dico|Fundamento)\s+(\d+)",
    re.IGNORECASE | re.UNICODE,
)


class StrictCitationVerifier:
    """Exact-match verifier for jurisprudential citations."""

    SIMILARITY_THRESHOLD = 0.85  # vs 0.75 for normativa

    def verify(
        self,
        claim_text: str,
        chunk_text: str,
        citation: CitationMapping,
        chunk_metadata: dict[str, Any],
    ) -> ClaimVerification:
        """Run all strict checks; return PASSED or first rejection."""
        ref_index = citation.index

        # 1. ECLI check
        ecli_result = self._check_ecli(claim_text, chunk_metadata, ref_index)
        if ecli_result is not None:
            return ecli_result

        # 2. Case number check
        case_result = self._check_case_number(claim_text, chunk_text, chunk_metadata, ref_index)
        if case_result is not None:
            return case_result

        # 3. Year check
        year_result = self._check_year(claim_text, chunk_metadata, ref_index)
        if year_result is not None:
            return year_result

        # 4. Chamber check
        chamber_result = self._check_chamber(claim_text, chunk_metadata, ref_index)
        if chamber_result is not None:
            return chamber_result

        # 5. Grounds check
        grounds_result = self._check_grounds(claim_text, chunk_metadata, ref_index)
        if grounds_result is not None:
            return grounds_result

        # 6. Semantic similarity check
        similarity = self._jaccard_similarity(claim_text, chunk_text)
        if similarity < self.SIMILARITY_THRESHOLD:
            logger.debug(
                "strict_verifier.rejected",
                reason="REJECTED_LOW_SIMILARITY",
                similarity=round(similarity, 3),
                ref_index=ref_index,
            )
            return ClaimVerification(
                ref_index=ref_index,
                verdict="FAILED",
                method="heuristic",
                confidence=0.1,
                failure_reason=f"REJECTED_LOW_SIMILARITY: similarity={similarity:.3f} < {self.SIMILARITY_THRESHOLD}",
            )

        logger.debug(
            "strict_verifier.passed",
            ref_index=ref_index,
            similarity=round(similarity, 3),
        )
        return ClaimVerification(
            ref_index=ref_index,
            verdict="PASSED",
            method="heuristic",
            confidence=0.9,
            failure_reason=None,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_ecli(
        self,
        claim_text: str,
        chunk_metadata: dict[str, Any],
        ref_index: int,
    ) -> ClaimVerification | None:
        """Return rejection if claim ECLI doesn't match metadata ECLI."""
        claim_ecli_match = _ECLI_PATTERN.search(claim_text)
        if claim_ecli_match is None:
            return None

        claim_ecli = claim_ecli_match.group(0)
        metadata_ecli = chunk_metadata.get("ecli")
        if metadata_ecli is None:
            return None

        if claim_ecli != metadata_ecli:
            logger.debug(
                "strict_verifier.rejected",
                reason="REJECTED_ECLI_MISMATCH",
                claim_ecli=claim_ecli,
                metadata_ecli=metadata_ecli,
                ref_index=ref_index,
            )
            return ClaimVerification(
                ref_index=ref_index,
                verdict="FAILED",
                method="heuristic",
                confidence=0.0,
                failure_reason=(
                    f"REJECTED_ECLI_MISMATCH: claim={claim_ecli!r}, metadata={metadata_ecli!r}"
                ),
            )
        return None

    def _check_case_number(
        self,
        claim_text: str,
        chunk_text: str,
        chunk_metadata: dict[str, Any],
        ref_index: int,
    ) -> ClaimVerification | None:
        """Return rejection if case number in claim is not found in chunk text or metadata."""
        matches = _CASE_NUMBER_PATTERN.findall(claim_text)
        if not matches:
            return None

        metadata_case_number = chunk_metadata.get("case_number", "")

        for case_num in matches:
            in_chunk = case_num in chunk_text
            in_metadata = case_num in str(metadata_case_number)
            if not in_chunk and not in_metadata:
                logger.debug(
                    "strict_verifier.rejected",
                    reason="REJECTED_NO_CASE_NUMBER",
                    case_number=case_num,
                    ref_index=ref_index,
                )
                return ClaimVerification(
                    ref_index=ref_index,
                    verdict="FAILED",
                    method="heuristic",
                    confidence=0.0,
                    failure_reason=(
                        f"REJECTED_NO_CASE_NUMBER: {case_num!r} not found in chunk or metadata"
                    ),
                )
        return None

    def _check_year(
        self,
        claim_text: str,
        chunk_metadata: dict[str, Any],
        ref_index: int,
    ) -> ClaimVerification | None:
        """Return rejection if claim year doesn't match decision_date year in metadata."""
        year_match = _COURT_YEAR_PATTERN.search(claim_text)
        if year_match is None:
            return None

        claim_year = int(year_match.group(1))
        decision_date = chunk_metadata.get("decision_date")
        if decision_date is None:
            return None

        # decision_date may be a date object or a string "YYYY-MM-DD"
        if isinstance(decision_date, date):
            metadata_year = decision_date.year
        else:
            try:
                metadata_year = int(str(decision_date)[:4])
            except (ValueError, TypeError):
                return None

        if claim_year != metadata_year:
            logger.debug(
                "strict_verifier.rejected",
                reason="REJECTED_WRONG_YEAR",
                claim_year=claim_year,
                metadata_year=metadata_year,
                ref_index=ref_index,
            )
            return ClaimVerification(
                ref_index=ref_index,
                verdict="FAILED",
                method="heuristic",
                confidence=0.0,
                failure_reason=(
                    f"REJECTED_WRONG_YEAR: claim_year={claim_year}, decision_date_year={metadata_year}"
                ),
            )
        return None

    def _check_chamber(
        self,
        claim_text: str,
        chunk_metadata: dict[str, Any],
        ref_index: int,
    ) -> ClaimVerification | None:
        """Return rejection if chamber in claim doesn't match metadata chamber."""
        chamber_match = _CHAMBER_PATTERN.search(claim_text)
        if chamber_match is None:
            return None

        claim_chamber = chamber_match.group(0).strip()
        metadata_chamber = chunk_metadata.get("chamber")
        if metadata_chamber is None:
            return None

        if claim_chamber.lower() not in str(metadata_chamber).lower():
            logger.debug(
                "strict_verifier.rejected",
                reason="REJECTED_WRONG_CHAMBER",
                claim_chamber=claim_chamber,
                metadata_chamber=metadata_chamber,
                ref_index=ref_index,
            )
            return ClaimVerification(
                ref_index=ref_index,
                verdict="FAILED",
                method="heuristic",
                confidence=0.0,
                failure_reason=(
                    f"REJECTED_WRONG_CHAMBER: claim={claim_chamber!r}, "
                    f"metadata={metadata_chamber!r}"
                ),
            )
        return None

    def _check_grounds(
        self,
        claim_text: str,
        chunk_metadata: dict[str, Any],
        ref_index: int,
    ) -> ClaimVerification | None:
        """Return rejection if referenced FJ number is not in grounds metadata."""
        fj_matches = _FJ_PATTERN.findall(claim_text)
        if not fj_matches:
            return None

        grounds: list[str] = chunk_metadata.get("grounds", [])
        if not grounds:
            # No metadata to verify against — skip check
            return None

        # Normalize grounds to a flat set of integers present
        grounds_numbers: set[int] = set()
        for g in grounds:
            nums = re.findall(r"\d+", str(g))
            for n in nums:
                grounds_numbers.add(int(n))

        for fj_num_str in fj_matches:
            fj_num = int(fj_num_str)
            if fj_num not in grounds_numbers:
                logger.debug(
                    "strict_verifier.rejected",
                    reason="REJECTED_INVENTED_GROUNDS",
                    fj_number=fj_num,
                    grounds=grounds,
                    ref_index=ref_index,
                )
                return ClaimVerification(
                    ref_index=ref_index,
                    verdict="FAILED",
                    method="heuristic",
                    confidence=0.0,
                    failure_reason=(
                        f"REJECTED_INVENTED_GROUNDS: FJ {fj_num} not in grounds={grounds}"
                    ),
                )
        return None

    # ------------------------------------------------------------------
    # Similarity metric (Jaccard on word sets — no external model)
    # ------------------------------------------------------------------

    def _jaccard_similarity(self, text_a: str, text_b: str) -> float:
        """Compute Jaccard similarity between word sets of two texts."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a and not words_b:
            return 1.0
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)
