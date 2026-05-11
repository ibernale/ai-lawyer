"""Integration test: parse → segment → entity extraction pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_txt_pipeline_parse_segment_entities():
    from lex_agents_documents.parsers.dispatcher import detect_and_parse
    from lex_agents_documents.entities import EntityExtractor

    raw = (FIXTURES / "contrato_simple.txt").read_bytes()
    doc = detect_and_parse(raw, "contrato.txt", "integ-001")

    assert doc.doc_id == "integ-001"
    assert len(doc.segments) > 0

    # At least one clausula segment
    types = {s.segment_type for s in doc.segments}
    assert "clausula" in types or "parrafo" in types

    # Entity extraction
    extractor = EntityExtractor(anthropic_client=None)
    entities = extractor.extract(doc.text, [s.text for s in doc.segments])

    # NIF should be found
    assert any(e for e in entities.parties)
    # Article reference
    assert any(e for e in entities.norms_referenced)


def test_resolucion_pipeline_segment_types():
    from lex_agents_documents.parsers.dispatcher import detect_and_parse

    raw = (FIXTURES / "resolucion_simple.txt").read_bytes()
    doc = detect_and_parse(raw, "resolucion.txt", "integ-002")

    seg_types = {s.segment_type for s in doc.segments}
    # Should detect resolution structural types
    resolution_types = {"antecedente", "fundamento", "acuerdo", "resolucion"}
    assert len(seg_types & resolution_types) > 0


def test_pipeline_segment_indices_are_sequential():
    from lex_agents_documents.parsers.dispatcher import detect_and_parse

    raw = (FIXTURES / "contrato_simple.txt").read_bytes()
    doc = detect_and_parse(raw, "contrato.txt", "integ-003")

    indices = [s.index for s in doc.segments]
    assert indices == list(range(1, len(indices) + 1)), "Segment indices must be sequential 1-based"


def test_pipeline_segment_ids_include_doc_id():
    from lex_agents_documents.parsers.dispatcher import detect_and_parse

    raw = (FIXTURES / "contrato_simple.txt").read_bytes()
    doc = detect_and_parse(raw, "contrato.txt", "integ-004")

    for seg in doc.segments:
        assert seg.segment_id.startswith("integ-004::")


def test_pipeline_llm_fallback_not_called_with_sufficient_entities():
    """Entity extractor must NOT call LLM when regex finds enough entities."""
    from lex_agents_documents.entities import EntityExtractor

    mock_client = MagicMock()
    extractor = EntityExtractor(anthropic_client=mock_client)

    # Rich text with many entities
    text = (
        "La sociedad A12345678 y B87654321 acuerdan según el art. 1254 CC "
        "y el BOE-A-2023-12345 de fecha 2023-06-01, con ECLI:ES:TS:2022:1234."
    )
    entities = extractor.extract(text)

    mock_client.messages.create.assert_not_called()
    assert len(entities.parties) >= 2
