"""Tests for procedural memory: store init, loader, injector matching, seed."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lex_agents_memory.types import ProceduralPattern
from lex_agents_memory.procedural.store import (
    _SCHEMA_SQL,
    _SELECT_ACTIVE,
    init_db,
    get_active_patterns,
)
from lex_agents_memory.procedural.loader import ProceduralLoader
from lex_agents_memory.procedural.injector import ProceduralInjector


# ── helpers ──────────────────────────────────────────────────────────────────

_REAL_SEED = Path("packages/memory/seed/procedural_patterns_seed.sql")


def _make_pattern(key: str, keywords: list[str] = (), output_types: list[str] = ()) -> ProceduralPattern:
    applies_when: dict = {}
    if keywords:
        applies_when["keywords"] = list(keywords)
    if output_types:
        applies_when["output_types"] = list(output_types)
    content = json.dumps({
        "applies_when": applies_when,
        "instructions": f"Instructions for {key}",
    })
    return ProceduralPattern(
        id=1,
        pattern_key=key,
        version=1,
        content=content,
        source="human:test",
        active=True,
    )


# ── store tests ───────────────────────────────────────────────────────────────

def test_init_db_creates_table(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    with sqlite3.connect(db) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert ("procedural_patterns",) in tables


def test_init_db_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    init_db(db)  # should not raise


def test_init_db_with_seed(tmp_path: Path) -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    db = tmp_path / "test.db"
    init_db(db, _REAL_SEED)
    patterns = get_active_patterns(db)
    assert len(patterns) == 7


def test_init_db_seed_skipped_if_not_empty(tmp_path: Path) -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    db = tmp_path / "test.db"
    init_db(db, _REAL_SEED)
    first_count = len(get_active_patterns(db))
    init_db(db, _REAL_SEED)  # second init — seed must not be applied again
    second_count = len(get_active_patterns(db))
    assert first_count == second_count


def test_get_active_patterns_missing_db(tmp_path: Path) -> None:
    result = get_active_patterns(tmp_path / "nope.db")
    assert result == []


def test_get_active_patterns_returns_only_active(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    content = json.dumps({"applies_when": {}, "instructions": "Test"})
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO procedural_patterns "
            "(pattern_key, version, content, source, created_at, updated_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("key:active", 1, content, "test", "2026-01-01", "2026-01-01", 1),
        )
        conn.execute(
            "INSERT INTO procedural_patterns "
            "(pattern_key, version, content, source, created_at, updated_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("key:inactive", 1, content, "test", "2026-01-01", "2026-01-01", 0),
        )
        conn.commit()
    patterns = get_active_patterns(db)
    keys = {p.pattern_key for p in patterns}
    assert "key:active" in keys
    assert "key:inactive" not in keys


# ── loader tests ──────────────────────────────────────────────────────────────

def test_loader_from_seed_in_memory() -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    loader = ProceduralLoader(seed_sql_path=_REAL_SEED)
    patterns = loader.load()
    assert len(patterns) == 7
    keys = {p.pattern_key for p in patterns}
    assert "output_template:dictamen" in keys
    assert "output_template:memo_comite" in keys


def test_loader_cached() -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    loader = ProceduralLoader(seed_sql_path=_REAL_SEED)
    p1 = loader.load()
    p2 = loader.load()
    assert p1 is p2


def test_loader_no_seed_returns_empty(tmp_path: Path) -> None:
    loader = ProceduralLoader(seed_sql_path=tmp_path / "nonexistent.sql")
    patterns = loader.load()
    assert patterns == []


def test_loader_from_db(tmp_path: Path) -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    db = tmp_path / "proc.db"
    loader = ProceduralLoader(db_path=db, seed_sql_path=_REAL_SEED)
    patterns = loader.load()
    assert len(patterns) == 7
    assert db.exists()


# ── injector tests ────────────────────────────────────────────────────────────

def test_injector_match_by_keyword() -> None:
    injector = ProceduralInjector()
    patterns = [
        _make_pattern("p1", keywords=["CRR III"]),
        _make_pattern("p2", keywords=["DORA"]),
    ]
    matched = injector.match("Consulta sobre CRR III y capital", None, patterns)
    keys = {p.pattern_key for p in matched}
    assert "p1" in keys
    assert "p2" not in keys


def test_injector_match_by_output_type() -> None:
    injector = ProceduralInjector()
    patterns = [
        _make_pattern("tmpl:dictamen", output_types=["dictamen"]),
        _make_pattern("tmpl:nota", output_types=["nota"]),
    ]
    matched = injector.match("alguna consulta jurídica", "dictamen", patterns)
    keys = {p.pattern_key for p in matched}
    assert "tmpl:dictamen" in keys
    assert "tmpl:nota" not in keys


def test_injector_match_keyword_and_type() -> None:
    injector = ProceduralInjector()
    p = _make_pattern("p1", keywords=["DORA"], output_types=["dictamen"])
    matched = injector.match("consulta DORA", "nota", [p])
    assert len(matched) == 1  # keyword matches even though type doesn't


def test_injector_match_empty_applies_when_always_matches() -> None:
    injector = ProceduralInjector()
    pattern = ProceduralPattern(
        id=1,
        pattern_key="always",
        version=1,
        content=json.dumps({"applies_when": {}, "instructions": "Always"}),
        source="test",
        active=True,
    )
    matched = injector.match("any query", "nota", [pattern])
    assert len(matched) == 1


def test_injector_match_case_insensitive() -> None:
    injector = ProceduralInjector()
    patterns = [_make_pattern("p1", keywords=["mifid"])]
    matched = injector.match("Consulta sobre MiFID II", None, patterns)
    assert len(matched) == 1


def test_injector_build_context_nonempty(tmp_path: Path) -> None:
    injector = ProceduralInjector()
    patterns = [_make_pattern("tmpl:dictamen", output_types=["dictamen"])]
    matched = injector.match("consulta", "dictamen", patterns)
    ctx = injector.build_context(matched)
    assert "## Patrones Procedimentales Aplicables" in ctx
    assert "tmpl:dictamen" in ctx


def test_injector_build_context_empty_returns_empty_string() -> None:
    injector = ProceduralInjector()
    ctx = injector.build_context([])
    assert ctx == ""


def test_seed_patterns_applies_when_parseable() -> None:
    """All seed patterns must have valid JSON content with applies_when."""
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    loader = ProceduralLoader(seed_sql_path=_REAL_SEED)
    patterns = loader.load()
    for p in patterns:
        aw = p.applies_when
        assert isinstance(aw, dict), f"{p.pattern_key}: applies_when must be a dict"


def test_seed_crr_transitional_triggers_on_keyword() -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    loader = ProceduralLoader(seed_sql_path=_REAL_SEED)
    injector = ProceduralInjector()
    patterns = loader.load()
    matched = injector.match("implicaciones del período transitorio de CRR III", None, patterns)
    keys = {p.pattern_key for p in matched}
    assert "routing:crr_transitional_caveat" in keys


def test_seed_mifid_check_triggers_on_keyword() -> None:
    if not _REAL_SEED.exists():
        pytest.skip("Seed file not found")
    loader = ProceduralLoader(seed_sql_path=_REAL_SEED)
    injector = ProceduralInjector()
    patterns = loader.load()
    matched = injector.match("¿aplica MiFID II a este instrumento financiero?", None, patterns)
    keys = {p.pattern_key for p in matched}
    assert "quality:mifid_applicability_check" in keys


# ── ProceduralPattern property tests ─────────────────────────────────────────

def test_procedural_pattern_properties() -> None:
    p = _make_pattern("test:key", keywords=["foo"], output_types=["dictamen"])
    assert isinstance(p.applies_when, dict)
    assert "foo" in p.applies_when.get("keywords", [])
    assert isinstance(p.instructions, str)
    assert "test:key" in p.instructions


def test_procedural_pattern_invalid_json_properties() -> None:
    p = ProceduralPattern(
        id=1,
        pattern_key="bad",
        version=1,
        content="not valid json",
        source="test",
        active=True,
    )
    # applies_when returns {} on parse error; instructions returns raw content
    assert p.applies_when == {}
    assert p.instructions == "not valid json"
