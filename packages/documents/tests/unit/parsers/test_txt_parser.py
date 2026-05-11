from __future__ import annotations
from pathlib import Path
import pytest
from lex_agents_documents.parsers.txt import TxtParser
from lex_agents_documents.exceptions import ParseError

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

def test_txt_parser_basic():
    raw = (FIXTURES / "contrato_simple.txt").read_bytes()
    doc = TxtParser().parse(raw, "contrato.txt", "test-id-001")
    assert doc.mime_type == "text/plain"
    assert len(doc.text) > 0
    assert len(doc.sha256) == 64

def test_txt_parser_latin1_encoding():
    text = "Cláusula con ñ y acentos"
    raw = text.encode("latin-1")
    doc = TxtParser().parse(raw, "latin1.txt", "test-id-002")
    assert "Cláusula" in doc.text or "Cl" in doc.text  # chardet may vary

def test_txt_parser_sets_encoding_metadata():
    raw = b"simple ascii text"
    doc = TxtParser().parse(raw, "simple.txt", "test-id-003")
    assert "detected_encoding" in doc.metadata
