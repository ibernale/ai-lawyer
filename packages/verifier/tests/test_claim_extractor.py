"""Tests for ClaimExtractor."""

from __future__ import annotations

from lex_agents_shared.types import CitationMapping
from lex_agents_verifier.claim_extractor import ClaimExtractor


def _mapping(index: int = 1) -> CitationMapping:
    return CitationMapping(
        index=index,
        chunk_id=f"chunk-{index}",
        source_id=f"source-{index}",
        hierarchy_path=f"CRR > art. {index}",
        fragment_text="texto del fragmento",
    )


def test_claim_with_ref() -> None:
    """Claim followed by [REF:1] within 200 chars → 1 claim with ref_index=1."""
    text = "el artículo 92 del CRR establece un ratio del 4,5% [REF:1]"
    extractor = ClaimExtractor()
    claims = extractor.extract(text, [_mapping(1)])

    assert len(claims) >= 1
    # At least one claim should have ref_index=1
    refs = [c.ref_index for c in claims]
    assert 1 in refs, f"Expected ref_index=1 in {refs}"


def test_uncited_claim() -> None:
    """Normative claim without nearby [REF:n] → ref_index=None."""
    text = "la Directiva 2013/36/UE prevé obligaciones de publicación"
    extractor = ClaimExtractor()
    claims = extractor.extract(text, [])

    assert len(claims) >= 1
    assert all(c.ref_index is None for c in claims), (
        f"Expected all ref_index=None, got {[c.ref_index for c in claims]}"
    )


def test_regulatory_body_no_ref() -> None:
    """Regulatory body mention without [REF:n] → ref_index=None."""
    text = "El BCE ha indicado que las entidades deben mantener capital adicional"
    extractor = ClaimExtractor()
    claims = extractor.extract(text, [])

    assert len(claims) >= 1
    bce_claims = [c for c in claims if "BCE" in c.text or "Banco" in c.text.title()]
    assert len(bce_claims) >= 1
    assert all(c.ref_index is None for c in claims)


def test_clean_text_no_claims() -> None:
    """Non-normative text → 0 claims extracted."""
    text = "El mercado de valores español ha experimentado volatilidad."
    extractor = ClaimExtractor()
    claims = extractor.extract(text, [])

    assert len(claims) == 0, f"Expected 0 claims, got {len(claims)}: {[c.text for c in claims]}"
