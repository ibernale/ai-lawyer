"""Tests for HeuristicVerifier."""

from __future__ import annotations

from lex_agents_verifier.claim_extractor import Claim
from lex_agents_verifier.heuristic_verifier import HeuristicVerifier


def _claim(text: str, ref_index: int | None = 1) -> Claim:
    return Claim(text=text, ref_index=ref_index, start_char=0, end_char=len(text))


def test_entity_match_passes() -> None:
    """Claim with article number matching in chunk → PASSED."""
    verifier = HeuristicVerifier()
    claim = _claim("artículo 92 establece un ratio de capital")
    chunk = (
        "El artículo 92 del Reglamento (UE) 575/2013 establece los requisitos de fondos "
        "propios. Las entidades deberán mantener en todo momento un ratio de capital de nivel 1 "
        "ordinario del 4,5 por ciento."
    )
    result = verifier.verify(claim, chunk)
    assert result.verdict == "PASSED", f"Expected PASSED, got {result.verdict} (confidence={result.confidence})"


def test_entity_match_fails() -> None:
    """Claim about artículo 92 against chunk about artículo 3 → FAILED or UNCERTAIN."""
    verifier = HeuristicVerifier()
    claim = _claim("artículo 92")
    chunk = "El artículo 3 regula el objeto y ámbito de aplicación de la presente norma."
    result = verifier.verify(claim, chunk)
    assert result.verdict in ("FAILED", "UNCERTAIN"), (
        f"Expected FAILED or UNCERTAIN, got {result.verdict}"
    )


def test_phrase_overlap_uncertain() -> None:
    """Paraphrase claim with no article numbers → UNCERTAIN (no entity match, moderate overlap)."""
    verifier = HeuristicVerifier()
    # Paraphrase — shares some words with chunk but no article number or norm ID
    claim = _claim("las entidades deben publicar información sobre capital")
    chunk = (
        "Las instituciones deberán divulgar datos relativos a sus fondos propios y "
        "requisitos de capital con arreglo a lo dispuesto en la normativa aplicable."
    )
    result = verifier.verify(claim, chunk)
    # No entity match (no numbers), low trigram overlap → UNCERTAIN or FAILED
    assert result.verdict in ("UNCERTAIN", "FAILED"), (
        f"Expected UNCERTAIN or FAILED, got {result.verdict}"
    )


def test_percentage_mismatch_fails() -> None:
    """Claim with 4,5% against chunk mentioning only 8% → FAILED (different entity)."""
    verifier = HeuristicVerifier()
    claim = _claim("ratio del 4,5%")
    chunk = "Las entidades deberán mantener un ratio del 8% de capital de nivel 1 total."
    result = verifier.verify(claim, chunk)
    # 4,5% not in chunk, 8% is → entity match fails → FAILED
    assert result.verdict in ("FAILED", "UNCERTAIN"), (
        f"Expected FAILED or UNCERTAIN, got {result.verdict}"
    )
