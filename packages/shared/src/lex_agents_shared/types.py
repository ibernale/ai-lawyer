"""Shared domain types — placeholder, to be completed in Fase 2."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Chunk types (Fase 2 will flesh these out fully)
# ---------------------------------------------------------------------------

class ChunkMetadata(BaseModel):
    """Metadata attached to every indexed legal chunk. See skill legal-chunking."""

    chunk_id: str = Field(description="sha256(source_id + '::' + hierarchy_path)")
    jurisdiction: Literal["ES", "EU", "GB"] = "EU"
    source: str = Field(description="BOE | EURLEX | BDESPAIN")
    source_id: str = Field(description="ELI URI, CELEX number, or BOE document ID")
    document_type: str = ""
    hierarchy_path: str = Field(description="e.g. 'CRR > Título II > art. 92 > apt. 1'")
    article_number: str | None = None
    section_type: str = "articulo"
    language: str = "es"
    publication_date: date = Field(default_factory=date.today)
    entry_into_force: date | None = None
    in_force_at_indexing: bool = True
    checksum: str = ""
    contextual_summary: str = ""


# ---------------------------------------------------------------------------
# Citation types
# ---------------------------------------------------------------------------

class CitationMapping(BaseModel):
    """Maps a [REF:n] index to its source chunk. See skill citation-format."""

    index: int = Field(ge=1, description="1-based [REF:n] index")
    chunk_id: str
    source_id: str
    hierarchy_path: str
    fragment_text: str
    fragment_offset: int = 0
    citation_type: Literal["normativa", "jurisprudencia"] = "normativa"


# ---------------------------------------------------------------------------
# Verification types (Fase 2 — verifier package)
# ---------------------------------------------------------------------------

class ClaimVerification(BaseModel):
    ref_index: int
    verdict: Literal["PASSED", "FAILED", "UNCERTAIN"] = "UNCERTAIN"
    method: Literal["heuristic", "llm_fallback"] = "heuristic"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    failure_reason: str | None = None


class VerificationReport(BaseModel):
    response_id: str
    claims_total: int = 0
    claims_passed: int = 0
    claims_failed: int = 0
    claims_uncertain: int = 0
    verifications: list[ClaimVerification] = Field(default_factory=list)
    llm_calls_made: int = 0
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    uncited_claims: list[str] = Field(
        default_factory=list,
        description="Normative claims with no [REF:n] annotation",
    )
    broken_refs: list[int] = Field(
        default_factory=list,
        description="[REF:n] indices that do not resolve to any chunk",
    )
    status: Literal["green", "amber", "red"] = Field(
        default="green",
        description=(
            "red: broken_refs>0 or any FAILED; "
            "amber: uncited_claims or UNCERTAIN; "
            "green: all PASSED, no uncited"
        ),
    )
    branch: str = Field(
        default="",
        description="Specialist branch that produced this response (empty string = single branch)",
    )


class AggregateVerificationReport(BaseModel):
    """Aggregated verification across multiple specialist branches."""

    response_id: str
    branch_reports: list[VerificationReport]  # one per branch
    overall_status: Literal["green", "amber", "red"]
    overall_claims_total: int
    overall_claims_passed: int
    overall_claims_failed: int
    overall_claims_uncertain: int
    overall_broken_refs: list[int]
    overall_uncited_claims: list[str]
    doc_broken_refs: list[int] = Field(
        default_factory=list,
        description="[DOC:s] indices that do not resolve to any segment",
    )
    # overall_status = "red" if any branch is red,
    # "amber" if any amber + no red, "green" if all green
