"""Tests for semantic memory: loader, injector, validator, budget cap."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from lex_agents_memory.semantic.loader import SemanticLoader
from lex_agents_memory.semantic.injector import SemanticInjector, _BUDGET_CHARS
from lex_agents_memory.semantic.validator import validate_all


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_yaml(tmp_path: Path, filename: str, content: dict) -> Path:
    p = tmp_path / filename
    p.write_text(yaml.dump(content, allow_unicode=True))
    return p


def _minimal_knowledge_dir(tmp_path: Path) -> Path:
    kd = tmp_path / "knowledge"
    kd.mkdir()
    _write_yaml(kd, "jurisdictions.yaml", {
        "_schema_version": "1.0",
        "_description": "test",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "jurisdictions": [
            {
                "code": "ES",
                "name": "España",
                "supervisor_prudential": "BdE",
                "supervisor_conduct": "CNMV",
                "supervisor_data": "AEPD",
                "currency": "EUR",
                "regime": "CRR/CRD",
            },
            {
                "code": "UK",
                "name": "Reino Unido",
                "supervisor_prudential": "PRA",
                "supervisor_conduct": "FCA",
                "supervisor_data": "ICO",
                "currency": "GBP",
                "regime": "UK CRR",
            },
        ],
    })
    _write_yaml(kd, "internal-glossary.yaml", {
        "_schema_version": "1.0",
        "_description": "test",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "glossary": [
            {"term": "DCN", "abbreviation": "DCN", "description": "Cumplimiento Normativo"},
        ],
    })
    _write_yaml(kd, "regulatory-frameworks.yaml", {
        "_schema_version": "1.0",
        "_description": "test",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "frameworks": [
            {
                "id": "CRR_III",
                "full_name": "Reglamento (UE) 2024/1623",
                "jurisdiction": "EU",
                "branches": ["regulatorio_bancario_ue_es"],
                "celex": "32024R1623",
            },
            {
                "id": "LEY_10_2014",
                "full_name": "Ley 10/2014",
                "jurisdiction": "ES",
                "branches": ["regulatorio_bancario_ue_es"],
                "celex": None,
            },
        ],
    })
    _write_yaml(kd, "output-templates.yaml", {
        "_schema_version": "1.0",
        "_description": "test",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "templates": [
            {
                "output_type": "dictamen",
                "structure": ["## 1. Objeto", "## 2. Marco", "## 3. Análisis"],
                "length_guidance": "600-1200 palabras",
                "audience": "Juristas internos",
                "mandatory_caveat": "Borrador asistido por IA. Requiere validación.",
                "tone": "Técnico-jurídico",
            },
        ],
    })
    return kd


# ── validator tests ───────────────────────────────────────────────────────────

def test_validate_all_ok(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    errors = validate_all(kd)
    assert errors == []


def test_validate_all_missing_header(tmp_path: Path) -> None:
    kd = tmp_path / "k"
    kd.mkdir()
    p = kd / "jurisdictions.yaml"
    p.write_text(yaml.dump({"jurisdictions": []}))
    errors = validate_all(kd)
    assert any("missing header keys" in e for e in errors)


def test_validate_all_missing_section(tmp_path: Path) -> None:
    kd = tmp_path / "k"
    kd.mkdir()
    p = kd / "jurisdictions.yaml"
    p.write_text(yaml.dump({
        "_schema_version": "1.0",
        "_description": "t",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        # missing 'jurisdictions' key
    }))
    errors = validate_all(kd)
    assert any("jurisdictions" in e for e in errors)


def test_validate_all_missing_field(tmp_path: Path) -> None:
    kd = tmp_path / "k"
    kd.mkdir()
    p = kd / "jurisdictions.yaml"
    p.write_text(yaml.dump({
        "_schema_version": "1.0",
        "_description": "t",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "jurisdictions": [{"code": "ES", "name": "España"}],  # missing required fields
    }))
    errors = validate_all(kd)
    assert any("supervisor_prudential" in e or "currency" in e for e in errors)


def test_validate_all_dir_not_found(tmp_path: Path) -> None:
    errors = validate_all(tmp_path / "nonexistent")
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_validate_all_yaml_parse_error(tmp_path: Path) -> None:
    kd = tmp_path / "k"
    kd.mkdir()
    (kd / "jurisdictions.yaml").write_text("key: [\nbad yaml")
    errors = validate_all(kd)
    assert any("YAML parse error" in e for e in errors)


# ── loader tests ──────────────────────────────────────────────────────────────

def test_load_all_returns_all_sections(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    loader = SemanticLoader(kd)
    data = loader.load_all()
    assert "jurisdictions" in data
    assert "glossary" in data
    assert "frameworks" in data
    assert "templates" in data


def test_load_all_cached(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    loader = SemanticLoader(kd)
    d1 = loader.load_all()
    d2 = loader.load_all()
    assert d1 is d2  # same object — cached


def test_load_all_missing_dir_returns_empty(tmp_path: Path) -> None:
    loader = SemanticLoader(tmp_path / "nope")
    data = loader.load_all()
    assert data == {}


def test_load_for_query_filters_jurisdictions(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    loader = SemanticLoader(kd)
    data = loader.load_for_query(jurisdictions=["ES"])
    codes = {e.content["code"] for e in data["jurisdictions"]}
    # ES requested + EU always included; UK should be absent
    assert "UK" not in codes


def test_load_for_query_always_includes_eu(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    loader = SemanticLoader(kd)
    data = loader.load_for_query(jurisdictions=["ES"])
    fw_ids = {e.content["id"] for e in data["frameworks"]}
    # CRR_III is EU-jurisdiction; should be included since EU always wanted
    assert "CRR_III" in fw_ids


def test_load_for_query_filters_template_by_output_type(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    loader = SemanticLoader(kd)
    data = loader.load_for_query(jurisdictions=["ES"], output_type="dictamen")
    assert len(data["templates"]) == 1
    assert data["templates"][0].content["output_type"] == "dictamen"


def test_load_for_query_unknown_output_type_empty_templates(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    loader = SemanticLoader(kd)
    data = loader.load_for_query(jurisdictions=["ES"], output_type="nota")
    # nota not in test fixtures
    assert data["templates"] == []


# ── injector tests ────────────────────────────────────────────────────────────

def test_injector_returns_nonempty_context(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    injector = SemanticInjector(SemanticLoader(kd))
    ctx = injector.build_context(jurisdictions=["ES"], output_type="dictamen")
    assert ctx != ""
    assert "## Memoria Semántica Institucional" in ctx


def test_injector_includes_jurisdiction_section(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    injector = SemanticInjector(SemanticLoader(kd))
    ctx = injector.build_context(jurisdictions=["ES"])
    assert "ES" in ctx


def test_injector_includes_template_section(tmp_path: Path) -> None:
    kd = _minimal_knowledge_dir(tmp_path)
    injector = SemanticInjector(SemanticLoader(kd))
    ctx = injector.build_context(jurisdictions=["ES"], output_type="dictamen")
    assert "dictamen" in ctx.lower()


def test_injector_budget_cap_truncates(tmp_path: Path) -> None:
    """Injector must not exceed _BUDGET_CHARS even with many frameworks."""
    kd = tmp_path / "k"
    kd.mkdir()
    # Write 200 frameworks to blow the budget
    big_frameworks = [
        {
            "id": f"FW_{i:03d}",
            "full_name": "X" * 200,
            "jurisdiction": "EU",
            "branches": ["test"],
            "celex": f"3{i:020d}",
        }
        for i in range(200)
    ]
    _write_yaml(kd, "regulatory-frameworks.yaml", {
        "_schema_version": "1.0",
        "_description": "t",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "frameworks": big_frameworks,
    })
    _write_yaml(kd, "jurisdictions.yaml", {
        "_schema_version": "1.0",
        "_description": "t",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "jurisdictions": [],
    })
    _write_yaml(kd, "internal-glossary.yaml", {
        "_schema_version": "1.0",
        "_description": "t",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "glossary": [],
    })
    _write_yaml(kd, "output-templates.yaml", {
        "_schema_version": "1.0",
        "_description": "t",
        "_last_updated": "2026-01-01",
        "_edit_policy": "PR-only",
        "templates": [],
    })
    injector = SemanticInjector(SemanticLoader(kd))
    ctx = injector.build_context(jurisdictions=["EU"])
    assert len(ctx) <= _BUDGET_CHARS + 200  # small tolerance for section headers


def test_injector_empty_dir_returns_empty_string(tmp_path: Path) -> None:
    injector = SemanticInjector(SemanticLoader(tmp_path / "nope"))
    ctx = injector.build_context(jurisdictions=["ES"])
    assert ctx == ""
