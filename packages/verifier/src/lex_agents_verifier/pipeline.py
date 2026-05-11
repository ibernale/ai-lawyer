"""Verifier pipeline — orchestrates extraction, heuristic, and LLM fallback."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog
from lex_agents_shared.anthropic_client import AnthropicClientWrapper
from lex_agents_shared.types import (
    AggregateVerificationReport,
    CitationMapping,
    ClaimVerification,
    VerificationReport,
)

from .citation_parser import CitationParser
from .claim_extractor import Claim, ClaimExtractor
from .doc_segment_verifier import DocSegmentVerifier
from .heuristic_verifier import HeuristicVerifier
from .llm_verifier import LLMVerifier

if TYPE_CHECKING:
    from lex_agents_documents.types import DocumentSegment

_DOC_REF_RE = re.compile(r"\[DOC:(\d+)\]")

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class VerifierPipeline:
    """Full verification pipeline: extraction → heuristic → LLM fallback."""

    _doc_verifier: DocSegmentVerifier = DocSegmentVerifier()

    def __init__(self, anthropic_client: AnthropicClientWrapper) -> None:
        self._client = anthropic_client

    async def run(
        self,
        response_id: str,
        answer_text: str,
        citations: list[CitationMapping],
        chunk_store: dict[str, str],
        branch: str = "",
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
        status: Literal["green", "amber", "red"]
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
            verified_at=datetime.now(UTC),
            uncited_claims=uncited_claims,
            broken_refs=broken_refs,
            status=status,
            branch=branch,
        )

    async def run_aggregate(
        self,
        branch_responses: list[tuple[str, str, list[CitationMapping], dict[str, str]]],
        response_id: str,
    ) -> AggregateVerificationReport:
        """Run verification across multiple specialist branches and aggregate results.

        Args:
            branch_responses: List of (branch_name, answer_text, citations, chunk_store) tuples.
            response_id: Shared response ID for the aggregate report.

        Returns:
            AggregateVerificationReport with per-branch reports and rolled-up totals.
        """
        branch_reports: list[VerificationReport] = []
        for branch_name, answer_text, citations, chunk_store in branch_responses:
            report = await self.run(
                response_id=response_id,
                answer_text=answer_text,
                citations=citations,
                chunk_store=chunk_store,
                branch=branch_name,
            )
            branch_reports.append(report)

        # Aggregate totals
        overall_claims_total = sum(r.claims_total for r in branch_reports)
        overall_claims_passed = sum(r.claims_passed for r in branch_reports)
        overall_claims_failed = sum(r.claims_failed for r in branch_reports)
        overall_claims_uncertain = sum(r.claims_uncertain for r in branch_reports)
        overall_broken_refs: list[int] = [
            ref for r in branch_reports for ref in r.broken_refs
        ]
        overall_uncited_claims: list[str] = [
            claim for r in branch_reports for claim in r.uncited_claims
        ]

        # Overall status: red if any red, amber if any amber + no red, green if all green
        statuses = {r.status for r in branch_reports}
        if "red" in statuses:
            overall_status: str = "red"
        elif "amber" in statuses:
            overall_status = "amber"
        else:
            overall_status = "green"

        logger.info(
            "verifier_pipeline.aggregate_complete",
            response_id=response_id,
            branch_count=len(branch_reports),
            overall_claims_total=overall_claims_total,
            overall_claims_passed=overall_claims_passed,
            overall_claims_failed=overall_claims_failed,
            overall_claims_uncertain=overall_claims_uncertain,
            overall_broken_refs_count=len(overall_broken_refs),
            overall_uncited_claims_count=len(overall_uncited_claims),
            overall_status=overall_status,
        )

        return AggregateVerificationReport(
            response_id=response_id,
            branch_reports=branch_reports,
            overall_status=overall_status,  # type: ignore[arg-type]
            overall_claims_total=overall_claims_total,
            overall_claims_passed=overall_claims_passed,
            overall_claims_failed=overall_claims_failed,
            overall_claims_uncertain=overall_claims_uncertain,
            overall_broken_refs=overall_broken_refs,
            overall_uncited_claims=overall_uncited_claims,
        )

    def verify_doc_segments(
        self,
        answer_text: str,
        segments: list[DocumentSegment],
    ) -> list[ClaimVerification]:
        """Verify all [DOC:s] citations in answer_text against the provided segments.

        For each [DOC:s] reference found in answer_text, extracts the surrounding
        context (±150 chars) and runs DocSegmentVerifier against the indexed segment.

        Args:
            answer_text: The agent answer containing [DOC:s] references.
            segments: Ordered list of DocumentSegment objects (1-based by index).

        Returns:
            List of ClaimVerification, one per [DOC:s] match found.
        """
        results: list[ClaimVerification] = []
        for match in _DOC_REF_RE.finditer(answer_text):
            s = int(match.group(1))
            if s < 1 or s > len(segments):
                results.append(ClaimVerification(
                    ref_index=s,
                    verdict="FAILED",
                    method="heuristic",
                    confidence=0.0,
                    failure_reason="REJECTED_BROKEN_DOC_REF",
                ))
                continue
            # Extract surrounding sentence for claim context
            start = max(0, match.start() - 150)
            end = min(len(answer_text), match.end() + 150)
            surrounding = answer_text[start:end]
            result = self._doc_verifier.verify(
                claim_text=surrounding,
                segment_text=segments[s - 1].text,
                segment_index=s,
            )
            results.append(result)
        return results
