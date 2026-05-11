"""Canonical parsing assets — raw bytes → CanonicalDocument JSON.

Reads from data/raw/<source>/, writes JSON to data/canonical/<source>/.
DataVersion = sha256 of concatenated canonical checksums → changes when
any underlying document changes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import structlog
from dagster import (
    AssetExecutionContext,
    DataVersion,
    Output,
    asset,
)
from lex_agents_ingest.canonical import RawDocument
from lex_agents_ingest.storage import IngestStorage

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("LEX_DATA_DIR", "data"))


def _parse_source(source_id: str) -> dict[str, Any]:
    """Load all raw files for source_id, parse to canonical, write JSON. Returns report."""
    from lex_agents_ingest.sources.boe import BoeSource
    from lex_agents_ingest.sources.eurlex import EurlexSource

    source_map: dict[str, Any] = {"boe": BoeSource, "eurlex": EurlexSource}
    try:
        from lex_agents_ingest.sources.aepd import AepdSource
        source_map["aepd"] = AepdSource
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.edpb import EdpbSource
        source_map["edpb"] = EdpbSource
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.bde import BdeSource
        source_map["bde"] = BdeSource
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.eba import EbaSource
        source_map["eba"] = EbaSource
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.esma import EsmaSource
        source_map["esma"] = EsmaSource
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.legislation_uk import LegislationUkSource
        source_map["legislation_uk"] = LegislationUkSource
    except ImportError:
        pass
    try:
        from lex_agents_ingest.sources.fca import FcaSource
        source_map["fca"] = FcaSource
    except ImportError:
        pass

    SourceClass = source_map.get(source_id)
    if SourceClass is None:
        return {"parsed": 0, "skipped": 0, "errors": 1, "parse_error_rate": 1.0}

    storage = IngestStorage(base_dir=_DATA_DIR)
    raw_dir = _DATA_DIR / "raw" / source_id
    if not raw_dir.exists():
        return {"parsed": 0, "skipped": 0, "errors": 0, "parse_error_rate": 0.0}

    src_instance = SourceClass()  # no http client needed for parse_to_canonical
    parsed = skipped = errors = 0

    for raw_path in raw_dir.iterdir():
        if raw_path.suffix not in {".xml", ".html", ".pdf", ".json"}:
            continue
        doc_id = raw_path.stem
        content_type = raw_path.suffix.lstrip(".")
        try:
            raw_bytes = raw_path.read_bytes()
            raw_doc = RawDocument(
                source=source_id,
                source_id=doc_id,
                raw_url=f"file://{raw_path}",
                content_type=content_type,  # type: ignore[arg-type]
                raw_bytes=raw_bytes,
            )
            canonical = src_instance.parse_to_canonical(raw_doc)
            result = storage.write_canonical(canonical)
            if result.skipped:
                skipped += 1
            else:
                parsed += 1
        except Exception as exc:
            errors += 1
            logger.error("canonical_parse_error", source=source_id, doc_id=doc_id, error=str(exc))

    total = parsed + skipped + errors
    error_rate = errors / total if total > 0 else 0.0
    return {"parsed": parsed, "skipped": skipped, "errors": errors, "parse_error_rate": error_rate}


def _canonical_checksum(source_id: str) -> str:
    """SHA-256 of all canonical JSON files sorted by name."""
    canon_dir = _DATA_DIR / "canonical" / source_id
    if not canon_dir.exists():
        return "empty"
    h = hashlib.sha256()
    for p in sorted(canon_dir.glob("*.json")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _make_canonical_asset(src_id: str, group: str, upstream: str) -> Any:
    @asset(
        name=f"{src_id}_canonical",
        group_name=group,
        compute_kind="parser",
        deps=[upstream],
        description=f"Parsed canonical JSON for {src_id}",
    )
    def _asset(context: AssetExecutionContext) -> Output[dict[str, Any]]:  # type: ignore[misc]
        report = _parse_source(src_id)
        checksum = _canonical_checksum(src_id)

        if report["parse_error_rate"] > 0.05:
            context.log.warning(
                f"{src_id} parse error rate {report['parse_error_rate']:.1%} exceeds 5%"
            )

        yield Output(
            value=report,
            data_version=DataVersion(checksum),
            metadata={
                "docs_parsed": report["parsed"],
                "docs_skipped": report["skipped"],
                "parse_errors": report["errors"],
                "parse_error_rate": report["parse_error_rate"],
            },
        )

    return _asset


boe_canonical = _make_canonical_asset("boe", "boe", "boe_raw")
eurlex_canonical = _make_canonical_asset("eurlex", "eurlex", "eurlex_raw")
aepd_canonical = _make_canonical_asset("aepd", "aepd", "aepd_raw")
edpb_canonical = _make_canonical_asset("edpb", "edpb", "edpb_raw")
bde_canonical = _make_canonical_asset("bde", "bde", "bde_raw")
eba_canonical = _make_canonical_asset("eba", "eba", "eba_raw")
esma_canonical = _make_canonical_asset("esma", "esma", "esma_raw")
legislation_uk_canonical = _make_canonical_asset("legislation_uk", "legislation_uk", "legislation_uk_raw")
fca_canonical = _make_canonical_asset("fca", "fca", "fca_raw")

ALL_CANONICAL_ASSETS = [
    boe_canonical, eurlex_canonical,
    aepd_canonical, edpb_canonical, bde_canonical, eba_canonical, esma_canonical,
    legislation_uk_canonical, fca_canonical,
]
