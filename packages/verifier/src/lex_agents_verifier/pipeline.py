"""Verifier pipeline — orchestrates extraction, heuristic, and LLM fallback."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from lex_agents_shared.types import CitationMapping, ClaimVerification, VerificationReport

from .citation_parser import CitationParser
from .claim_extractor import Claim, ClaimExtractor
from .heuristic_verifier import HeuristicVerifier
from .llm_verifier import LLMVerifier

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class VerifierPipeline:
    """Full verification pipeline: extraction → heuristic → LLM fallback."""

    def __init__(self, anthropic_client: AnthropicClientWrapper) -> None:
        self._client = anthropic_client

    async def run(
        self,
        response_id: str,
        answer_text: str,
        citations: list[CitationMapping],
        chunk_store: dict[str, str],
    ) -> VerificationReport:
        """Run the full verification pipeline and return a VerificationReport."""

        # Step 1: Extract normative claims
        extractor = ClaimExtractor()
        claims: list[Claim] = extractor.extract(answer_text, citations)

        # Step 2: Find broken references
        parser = CitationParser()
        broken_refs: list[int] = parser.find_broken_refs(answer_text, citations)

        # Step 3: Heuristic verification for cited claims
        heuristic = HeuristicVerifier()
        verifications: list[ClaimVerification] = []
        uncertain_with_meta: list[tuple[Claim, str, ClaimVerification]] = []

        for claim in claims:
            if claim.ref_index is None:
                continue

            citation = parser.resolve(claim.ref_index, citations)
            if citation is None:
                # Ref not in mapping — skip (broken ref already captured)
                continue

            chunk_text = chunk_store.get(citation.chunk_id, citation.fragment_text)
            cv = heuristic.verify(claim, chunk_text)
            # Ensure ref_index is set correctly
            cv = ClaimVerification(
                ref_index=claim.ref_index,
                verdict=cv.verdict,
                method=cv.method,
                confidence=cv.confidence,
                failure_reason=cv.failure_reason,
            )
            verifications.append(cv)

            if cv.verdict == "UNCERTAIN":
                uncertain_with_meta.append((claim, chunk_text, cv))

        # Step 4: Collect uncited claims
        uncited_claims: list[str] = [
            claim.text for claim in claims if claim.ref_index is None
        ]

        # Step 5: LLM fallback for UNCERTAIN claims
        llm_calls_made = 0
        if uncertain_with_meta:
            llm_verifier = LLMVerifier(self._client)
            updated = await llm_verifier.verify_uncertain(uncertain_with_meta)
            llm_calls_made = len([cv for cv in updated if cv.method == "llm_fallback"])

            # Replace UNCERTAIN verifications with LLM results using positional map
            # uncertain_with_meta[j] holds (claim, chunk_text, verifications[vi])
            # Build map: verification object id → updated result
            id_to_updated: dict[int, ClaimVerification] = {}
            for j, (_, _, orig_cv) in enumerate(uncertain_with_meta):
                id_to_updated[id(orig_cv)] = updated[j]

            verifications = [
                id_to_updated.get(id(cv), cv) for cv in verifications
            ]

        # Step 6: Compute summary counts
        claims_passed = sum(1 for cv in verifications if cv.verdict == "PASSED")
        claims_failed = sum(1 for cv in verifications if cv.verdict == "FAILED")
        claims_uncertain = sum(1 for cv in verifications if cv.verdict == "UNCERTAIN")
        claims_total = len(verifications) + len(uncited_claims)

        # Step 6: Determine overall status
        if broken_refs or claims_failed > 0:
            status = "red"
        elif uncited_claims or claims_uncertain > 0:
            status = "amber"
        else:
            status = "green"

        logger.info(
            "verifier_pipeline.complete",
            response_id=response_id,
            claims_total=claims_total,
            claims_passed=claims_passed,
            claims_failed=claims_failed,
            claims_uncertain=claims_uncertain,
            broken_refs=broken_refs,
            uncited_claims_count=len(uncited_claims),
            llm_calls_made=llm_calls_made,
            status=status,
        )

        return VerificationReport(
            response_id=response_id,
            claims_total=claims_total,
            claims_passed=claims_passed,
            claims_failed=claims_failed,
            claims_uncertain=claims_uncertain,
            verifications=verifications,
            llm_calls_made=llm_calls_made,
            verified_at=datetime.now(timezone.utc),
            uncited_claims=uncited_claims,
            broken_refs=broken_refs,
            status=status,
        )
