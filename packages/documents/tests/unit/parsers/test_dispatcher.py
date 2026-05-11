from __future__ import annotations
from pathlib import Path
import pytest
from lex_agents_documents.parsers.dispatcher import detect_and_parse
from lex_agents_documents.exceptions import UnsupportedFormatError, DocumentTooLargeError

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

def test_dispatcher_routes_txt():
    raw = (FIXTURES / "contrato_simple.txt").read_bytes()
    doc = detect_and_parse(raw, "contrato.txt", "test-disp-001")
    assert doc.mime_type == "text/plain"
    assert len(doc.segments) > 0

def test_dispatcher_raises_unsupported():
    raw = b"GIF89a\x01\x00\x01\x00"
    with pytest.raises(UnsupportedFormatError):
        detect_and_parse(raw, "image.gif", "test-disp-002")

def test_dispatcher_raises_too_large():
    raw = b"x" * (51 * 1024 * 1024)
    with pytest.raises(DocumentTooLargeError):
        detect_and_parse(raw, "big.txt", "test-disp-003")

def test_dispatcher_segments_after_parse():
    raw = (FIXTURES / "resolucion_simple.txt").read_bytes()
    doc = detect_and_parse(raw, "resolucion.txt", "test-disp-004")
    types = {s.segment_type for s in doc.segments}
    # Should contain at least antecedente or fundamento
    assert types & {"antecedente", "fundamento", "acuerdo", "parrafo"}
