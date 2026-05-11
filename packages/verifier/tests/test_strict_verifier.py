"""Unit tests for StrictCitationVerifier — ADR 0024."""

from __future__ import annotations

from datetime import date

import pytest
from lex_agents_shared.types import CitationMapping
from lex_agents_verifier.strict_verifier import StrictCitationVerifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _citation(index: int = 1, citation_type: str = "jurisprudencia") -> CitationMapping:
    return CitationMapping(
        index=index,
        chunk_id=f"chunk-{index}",
        source_id="ECLI:ES:TS:2024:1234",
        hierarchy_path="STS > FJ 1",
        fragment_text="fragmento de prueba",
        citation_type=citation_type,  # type: ignore[arg-type]
    )


def _verifier() -> StrictCitationVerifier:
    return StrictCitationVerifier()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_correct_citation_passes() -> None:
    """Valid case number in chunk, matching year, correct sala → PASSED."""
    verifier = _verifier()
    claim = (
        "La STS de 2024 en el recurso 1234/2024 de la Sala de lo Civil "
        "establece que el banco debe responder."
    )
    chunk = (
        "Tribunal Supremo, recurso 1234/2024. La Sala de lo Civil del Tribunal Supremo, "
        "en su sentencia de 2024, establece que el banco debe responder por los daños causados. "
        "El ponente examina la responsabilidad contractual aplicando los artículos pertinentes."
    )
    metadata = {
        "decision_date": date(2024, 3, 15),
        "chamber": "Sala de lo Civil",
        "case_number": "1234/2024",
    }
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "PASSED", f"Expected PASSED, got {result.verdict}: {result.failure_reason}"


@pytest.mark.unit
def test_wrong_case_number_rejected() -> None:
    """Claim says 1234/2024, chunk has 5678/2024 → REJECTED_NO_CASE_NUMBER."""
    verifier = _verifier()
    claim = "La STS recurso 1234/2024 establece la doctrina sobre responsabilidad."
    chunk = "Tribunal Supremo, recurso 5678/2024 trata sobre responsabilidad contractual."
    metadata: dict = {}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_NO_CASE_NUMBER" in result.failure_reason


@pytest.mark.unit
def test_case_number_not_in_chunk_rejected() -> None:
    """Claim mentions case number, not present in chunk text or metadata → REJECTED."""
    verifier = _verifier()
    claim = "Según la STS recurso 9999/2023, el banco debe indemnizar al cliente."
    chunk = "El Tribunal Supremo ha estudiado varios recursos sobre responsabilidad bancaria."
    metadata = {"case_number": "1111/2020"}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_NO_CASE_NUMBER" in result.failure_reason


@pytest.mark.unit
def test_wrong_year_rejected() -> None:
    """Claim says 2023, decision_date is 2022 → REJECTED_WRONG_YEAR."""
    verifier = _verifier()
    claim = "La sentencia de 2023 del Tribunal Supremo establece la doctrina aplicable."
    chunk = (
        "Tribunal Supremo. Sentencia de 2022. "
        "La sala examina el caso con atención a los precedentes doctrinales establecidos."
    )
    metadata = {"decision_date": date(2022, 6, 10)}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_WRONG_YEAR" in result.failure_reason


@pytest.mark.unit
def test_wrong_chamber_rejected() -> None:
    """Claim says Sala de lo Civil, metadata says Sala de lo Contencioso → REJECTED."""
    verifier = _verifier()
    claim = (
        "La Sala de lo Civil del Tribunal Supremo, en sentencia de 2024, "
        "establece que el contrato es nulo."
    )
    chunk = (
        "El tribunal examina el caso de nulidad contractual en el año 2024 y concluye "
        "que las condiciones generales son abusivas conforme a la jurisprudencia vigente."
    )
    metadata = {
        "decision_date": date(2024, 1, 20),
        "chamber": "Sala de lo Contencioso-Administrativo",
    }
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_WRONG_CHAMBER" in result.failure_reason


@pytest.mark.unit
def test_invented_fj_rejected() -> None:
    """Claim says FJ 15, grounds = [FJ 1, FJ 2] → REJECTED_INVENTED_GROUNDS."""
    verifier = _verifier()
    claim = (
        "Como establece el FJ 15 de la sentencia, la entidad financiera incumplió "
        "su deber de información."
    )
    chunk = (
        "Fundamento Jurídico 1: La entidad tenía obligación de informar. "
        "Fundamento Jurídico 2: El incumplimiento genera responsabilidad."
    )
    metadata = {"grounds": ["FJ 1", "FJ 2"]}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_INVENTED_GROUNDS" in result.failure_reason


@pytest.mark.unit
def test_ecli_mismatch_rejected() -> None:
    """Claim has ECLI:ES:TS:2024:1234, metadata has ECLI:ES:TS:2024:9999 → REJECTED."""
    verifier = _verifier()
    claim = (
        "La resolución ECLI:ES:TS:2024:1234 del Tribunal Supremo establece "
        "los criterios de responsabilidad."
    )
    chunk = (
        "Tribunal Supremo. Sentencia ECLI:ES:TS:2024:9999. "
        "Los criterios de responsabilidad se examinan en detalle."
    )
    metadata = {"ecli": "ECLI:ES:TS:2024:9999"}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_ECLI_MISMATCH" in result.failure_reason


@pytest.mark.unit
def test_ecli_correct_passes() -> None:
    """Matching ECLI in claim and metadata → not rejected by ECLI check."""
    verifier = _verifier()
    claim = (
        "La resolución ECLI:ES:TS:2024:5555 establece que la entidad debe indemnizar "
        "por los daños causados al cliente en el contrato suscrito."
    )
    chunk = (
        "ECLI:ES:TS:2024:5555 — Tribunal Supremo. La entidad debe indemnizar por los daños "
        "causados al cliente en el contrato suscrito según la doctrina establecida."
    )
    metadata = {"ecli": "ECLI:ES:TS:2024:5555"}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "PASSED", (
        f"Expected PASSED, got {result.verdict}: {result.failure_reason}"
    )


@pytest.mark.unit
def test_no_case_number_in_claim_skips_check() -> None:
    """Claim has no case number pattern → case number check skipped, no rejection from it."""
    verifier = _verifier()
    claim = (
        "La doctrina jurisprudencial del Tribunal Supremo establece que la entidad "
        "debe responder por los daños causados al cliente en operaciones de inversión."
    )
    chunk = (
        "El Tribunal Supremo establece en su jurisprudencia consolidada que la entidad "
        "debe responder por los daños causados al cliente en operaciones de inversión "
        "cuando no cumple con su deber de información previo."
    )
    metadata: dict = {}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    # Should not fail with REJECTED_NO_CASE_NUMBER
    assert result.failure_reason is None or "REJECTED_NO_CASE_NUMBER" not in (
        result.failure_reason or ""
    )


@pytest.mark.unit
def test_no_chamber_in_claim_skips_check() -> None:
    """Claim doesn't mention sala → chamber check skipped, no rejection from it."""
    verifier = _verifier()
    claim = (
        "En la sentencia de 2024 recurso 7777/2024, el tribunal estableció "
        "que el contrato es válido y vinculante para las partes."
    )
    chunk = (
        "Tribunal Supremo recurso 7777/2024. Sentencia de 2024. "
        "El tribunal estableció que el contrato es válido y vinculante para las partes "
        "según las condiciones pactadas en el mismo."
    )
    metadata = {
        "decision_date": date(2024, 5, 1),
        "case_number": "7777/2024",
        "chamber": "Sala de lo Civil",
    }
    result = verifier.verify(claim, chunk, _citation(), metadata)
    # Should not be rejected for chamber mismatch
    assert result.failure_reason is None or "REJECTED_WRONG_CHAMBER" not in (
        result.failure_reason or ""
    )


@pytest.mark.unit
def test_no_fj_in_claim_skips_check() -> None:
    """Claim doesn't mention FJ → grounds check skipped, no rejection from it."""
    verifier = _verifier()
    claim = (
        "La sentencia del Tribunal Supremo de 2024 en el recurso 2222/2024 "
        "establece que el banco incurrió en negligencia."
    )
    chunk = (
        "Tribunal Supremo recurso 2222/2024. La entidad incurrió en negligencia "
        "al no cumplir con los estándares de diligencia exigibles en 2024 "
        "conforme a la normativa vigente."
    )
    metadata = {
        "decision_date": date(2024, 2, 14),
        "case_number": "2222/2024",
        "grounds": ["FJ 1", "FJ 2", "FJ 3"],
    }
    result = verifier.verify(claim, chunk, _citation(), metadata)
    # Should not fail with REJECTED_INVENTED_GROUNDS
    assert result.failure_reason is None or "REJECTED_INVENTED_GROUNDS" not in (
        result.failure_reason or ""
    )


@pytest.mark.unit
def test_low_similarity_rejected() -> None:
    """Claim and chunk share almost no words → REJECTED_LOW_SIMILARITY."""
    verifier = _verifier()
    claim = "El banco debe restituir las cantidades cobradas indebidamente al consumidor."
    chunk = (
        "El arrendatario tiene derecho a la prórroga forzosa del contrato de arrendamiento "
        "urbano según la legislación vigente aplicable a viviendas habituales."
    )
    metadata: dict = {}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    assert result.verdict == "FAILED"
    assert result.failure_reason is not None
    assert "REJECTED_LOW_SIMILARITY" in result.failure_reason


@pytest.mark.unit
def test_high_similarity_passes() -> None:
    """Claim and chunk overlap well → not rejected by similarity check."""
    verifier = _verifier()
    claim = (
        "El banco debe informar al cliente sobre los riesgos del producto financiero "
        "antes de la contratación conforme a la normativa MiFID."
    )
    chunk = (
        "La entidad bancaria tiene la obligación de informar al cliente sobre los riesgos "
        "del producto financiero antes de la contratación, conforme a la normativa MiFID "
        "y a la doctrina jurisprudencial consolidada del Tribunal Supremo en la materia."
    )
    metadata: dict = {}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    # Should not be rejected for low similarity
    assert result.failure_reason is None or "REJECTED_LOW_SIMILARITY" not in (
        result.failure_reason or ""
    )


@pytest.mark.unit
def test_claim_without_metadata_graceful() -> None:
    """chunk_metadata = {} → checks requiring metadata are skipped, no crash."""
    verifier = _verifier()
    claim = (
        "La sentencia de 2023 del Tribunal Supremo en recurso 1111/2023 "
        "estableció que la cláusula suelo es nula de pleno derecho."
    )
    chunk = (
        "Tribunal Supremo recurso 1111/2023. La sentencia de 2023 estableció "
        "que la cláusula suelo es nula de pleno derecho según doctrina consolidada."
    )
    metadata: dict = {}
    # Should not raise an exception
    result = verifier.verify(claim, chunk, _citation(), metadata)
    # With empty metadata, year/chamber/ECLI checks are skipped; case number IS in chunk
    assert result is not None
    assert result.verdict in ("PASSED", "FAILED", "UNCERTAIN")


@pytest.mark.unit
def test_obiter_claim_passes_without_case_number() -> None:
    """Claim describes obiter dictum (no case number mentioned) → no case number rejection."""
    verifier = _verifier()
    claim = (
        "A mayor abundamiento, el Tribunal Supremo ha señalado que la entidad "
        "debe actuar con diligencia en la comercialización de productos de inversión "
        "y proporcionar información completa y comprensible al cliente."
    )
    chunk = (
        "El Tribunal Supremo ha señalado en obiter dictum que la entidad "
        "debe actuar con la máxima diligencia en la comercialización de productos "
        "de inversión, proporcionando información completa y comprensible al cliente "
        "antes de la contratación, como principio general del ordenamiento."
    )
    metadata: dict = {}
    result = verifier.verify(claim, chunk, _citation(), metadata)
    # No case number in claim → case number check is skipped entirely
    assert result.failure_reason is None or "REJECTED_NO_CASE_NUMBER" not in (
        result.failure_reason or ""
    )
    assert result.verdict == "PASSED", (
        f"Expected PASSED for obiter claim, got {result.verdict}: {result.failure_reason}"
    )
