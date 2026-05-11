"""Chaos tests for the verifier pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lex_agents_shared.types import CitationMapping, ClaimVerification
from lex_agents_verifier.pipeline import VerifierPipeline


def _make_mapping(index: int = 1, chunk_id: str = "chunk-1") -> CitationMapping:
    return CitationMapping(
        index=index,
        chunk_id=chunk_id,
        source_id="source-1",
        hierarchy_path="CRR > art. 92",
        fragment_text=(
            "El artículo 92 del Reglamento 575/2013 establece los requisitos de fondos propios. "
            "Las entidades deben mantener un ratio del 4,5 por ciento de capital ordinario."
        ),
    )


def _make_client() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_broken_ref_detected() -> None:
    """[REF:99] in text with only index=1 in mapping → broken_refs=[99], status='red'."""
    client = _make_client()
    pipeline = VerifierPipeline(anthropic_client=client)

    answer_text = (
        "Según la normativa aplicable, las entidades deben mantener capital [REF:99]."
    )
    citations = [_make_mapping(index=1)]
    chunk_store = {"chunk-1": "texto del chunk"}

    # Mock LLM verifier to avoid real API calls
    with patch(
        "lex_agents_verifier.pipeline.LLMVerifier.verify_uncertain",
        new=AsyncMock(side_effect=lambda claims_with_chunks: [cv for _, _, cv in claims_with_chunks]),
    ):
        report = await pipeline.run(
            response_id="test-broken",
            answer_text=answer_text,
            citations=citations,
            chunk_store=chunk_store,
        )

    assert 99 in report.broken_refs, f"Expected 99 in broken_refs, got {report.broken_refs}"
    assert report.status == "red", f"Expected status='red', got {report.status!r}"


@pytest.mark.asyncio
async def test_uncited_claim_detected() -> None:
    """Normative claim phrase with no [REF:n] nearby → uncited_claims non-empty."""
    client = _make_client()
    pipeline = VerifierPipeline(anthropic_client=client)

    # Contains a normative norm name but no [REF:n] anywhere near it
    answer_text = (
        "La Directiva 2013/36/UE prevé obligaciones de publicación para las entidades "
        "de crédito. Esta norma es de obligado cumplimiento."
    )
    citations = []
    chunk_store: dict[str, str] = {}

    with patch(
        "lex_agents_verifier.pipeline.LLMVerifier.verify_uncertain",
        new=AsyncMock(side_effect=lambda claims_with_chunks: [cv for _, _, cv in claims_with_chunks]),
    ):
        report = await pipeline.run(
            response_id="test-uncited",
            answer_text=answer_text,
            citations=citations,
            chunk_store=chunk_store,
        )

    assert len(report.uncited_claims) > 0, (
        f"Expected uncited_claims to be non-empty, got {report.uncited_claims}"
    )


@pytest.mark.asyncio
async def test_all_pass_green() -> None:
    """Pipeline correctly yields green when heuristic returns all PASSED and no broken refs."""
    from lex_agents_verifier.claim_extractor import Claim

    client = _make_client()
    pipeline = VerifierPipeline(anthropic_client=client)

    answer_text = "El artículo 92 del Reglamento 575/2013 establece un ratio del 4,5% [REF:1]."
    mapping = _make_mapping(index=1, chunk_id="chunk-1")
    chunk_store = {
        "chunk-1": (
            "El artículo 92 del Reglamento 575/2013 establece los requisitos de fondos propios. "
            "Las entidades deben mantener un ratio del 4,5 por ciento de capital ordinario."
        )
    }

    # Stub heuristic to PASSED for all claims (testing pipeline orchestration, not heuristic logic)
    def _stub_heuristic(claim: Claim, chunk_text: str) -> ClaimVerification:
        return ClaimVerification(
            ref_index=claim.ref_index or 1,
            verdict="PASSED",
            method="heuristic",
            confidence=0.9,
        )

    with (
        patch("lex_agents_verifier.pipeline.HeuristicVerifier.verify", side_effect=_stub_heuristic),
        patch(
            "lex_agents_verifier.pipeline.LLMVerifier.verify_uncertain",
            new=AsyncMock(return_value=[]),
        ),
    ):
        report = await pipeline.run(
            response_id="test-green",
            answer_text=answer_text,
            citations=[mapping],
            chunk_store=chunk_store,
        )

    assert report.broken_refs == [], f"Unexpected broken_refs: {report.broken_refs}"
    assert report.status == "green", (
        f"Expected status='green', got {report.status!r}. "
        f"failed={report.claims_failed}, uncertain={report.claims_uncertain}, "
        f"uncited={report.uncited_claims}"
    )
