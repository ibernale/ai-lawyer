"""Unit tests for commercial source stubs (Aranzadi, La Ley, Tirant). ADR 0029."""

from __future__ import annotations

from pathlib import Path

import pytest

from lex_agents_ingest.sources.aranzadi import AranzadiSource
from lex_agents_ingest.sources.laley import LaLeySource
from lex_agents_ingest.sources.tirant import TirantSource
from lex_agents_shared.exceptions import CommercialSourceDisabledError


@pytest.mark.unit
async def test_aranzadi_raises_without_fixture() -> None:
    source = AranzadiSource()
    with pytest.raises(CommercialSourceDisabledError):
        await source.list_documents()


@pytest.mark.unit
async def test_laley_raises_without_fixture() -> None:
    source = LaLeySource()
    with pytest.raises(CommercialSourceDisabledError):
        await source.list_documents()


@pytest.mark.unit
async def test_tirant_raises_without_fixture() -> None:
    source = TirantSource()
    with pytest.raises(CommercialSourceDisabledError):
        await source.list_documents()


@pytest.mark.unit
def test_aranzadi_fixture_mode_does_not_raise(tmp_path: Path) -> None:
    source = AranzadiSource(fixture_path=tmp_path)
    # _require_license() must not raise when fixture_path is set
    source._require_license()


@pytest.mark.unit
def test_laley_fixture_mode_does_not_raise(tmp_path: Path) -> None:
    source = LaLeySource(fixture_path=tmp_path)
    source._require_license()


@pytest.mark.unit
def test_tirant_fixture_mode_does_not_raise(tmp_path: Path) -> None:
    source = TirantSource(fixture_path=tmp_path)
    source._require_license()


@pytest.mark.unit
def test_aranzadi_error_contains_adr_0029() -> None:
    source = AranzadiSource()
    with pytest.raises(CommercialSourceDisabledError, match="ADR 0029"):
        source._require_license()


@pytest.mark.unit
def test_laley_error_contains_adr_0029() -> None:
    source = LaLeySource()
    with pytest.raises(CommercialSourceDisabledError, match="ADR 0029"):
        source._require_license()


@pytest.mark.unit
def test_tirant_error_contains_adr_0029() -> None:
    source = TirantSource()
    with pytest.raises(CommercialSourceDisabledError, match="ADR 0029"):
        source._require_license()


@pytest.mark.unit
def test_aranzadi_source_id() -> None:
    assert AranzadiSource.source_id == "aranzadi"


@pytest.mark.unit
def test_laley_source_id() -> None:
    assert LaLeySource.source_id == "laley"


@pytest.mark.unit
def test_tirant_source_id() -> None:
    assert TirantSource.source_id == "tirant"
