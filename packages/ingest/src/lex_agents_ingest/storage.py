"""Idempotent file-based storage for raw and canonical documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import structlog

from lex_agents_ingest.canonical import CanonicalDocument, RawDocument

logger: structlog.BoundLogger = structlog.get_logger(__name__)


@dataclass
class StorageResult:
    skipped: bool
    written: bool
    path: Path


class IngestStorage:
    """Read/write raw and canonical documents under *base_dir*.

    Layout::

        <base_dir>/raw/<source>/<source_id>.<ext>
        <base_dir>/canonical/<source>/<source_id>.json
    """

    def __init__(self, base_dir: str | Path = "data") -> None:
        self._base = Path(base_dir)

    # ------------------------------------------------------------------
    # Raw
    # ------------------------------------------------------------------

    def write_raw(self, doc: RawDocument) -> StorageResult:
        dest = self._raw_path(doc.source, doc.source_id, doc.content_type)
        if dest.exists():
            existing_checksum = self._read_raw_checksum(dest)
            if existing_checksum == doc.checksum:
                logger.debug("raw_skipped", source_id=doc.source_id)
                return StorageResult(skipped=True, written=False, path=dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(doc.raw_bytes)
        logger.info("raw_written", source_id=doc.source_id, path=str(dest))
        return StorageResult(skipped=False, written=True, path=dest)

    def read_raw(self, source: str, source_id: str, content_type: str) -> bytes | None:
        dest = self._raw_path(source, source_id, content_type)
        if not dest.exists():
            return None
        return dest.read_bytes()

    # ------------------------------------------------------------------
    # Canonical
    # ------------------------------------------------------------------

    def write_canonical(self, doc: CanonicalDocument) -> StorageResult:
        dest = self._canonical_path(doc.source, doc.source_id)
        if dest.exists():
            try:
                existing = CanonicalDocument.model_validate_json(dest.read_text())
                if existing.checksum == doc.checksum:
                    logger.debug("canonical_skipped", source_id=doc.source_id)
                    return StorageResult(skipped=True, written=False, path=dest)
            except Exception:
                pass
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(doc.model_dump_json(indent=2))
        logger.info("canonical_written", source_id=doc.source_id, path=str(dest))
        return StorageResult(skipped=False, written=True, path=dest)

    def read_canonical(self, source: str, source_id: str) -> CanonicalDocument | None:
        dest = self._canonical_path(source, source_id)
        if not dest.exists():
            return None
        return CanonicalDocument.model_validate_json(dest.read_text())

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _raw_path(self, source: str, source_id: str, content_type: str) -> Path:
        safe_id = source_id.replace("/", "_").replace(":", "_")
        return self._base / "raw" / source / f"{safe_id}.{content_type}"

    def _canonical_path(self, source: str, source_id: str) -> Path:
        safe_id = source_id.replace("/", "_").replace(":", "_")
        return self._base / "canonical" / source / f"{safe_id}.json"

    @staticmethod
    def _read_raw_checksum(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ------------------------------------------------------------------
    # Canonical listing
    # ------------------------------------------------------------------

    def list_canonical(self, source: str) -> list[CanonicalDocument]:
        """Load all canonical documents for a given source."""
        src_dir = self._base / "canonical" / source
        if not src_dir.exists():
            return []
        docs = []
        for p in sorted(src_dir.glob("*.json")):
            try:
                docs.append(CanonicalDocument.model_validate(json.loads(p.read_text())))
            except Exception as exc:
                logger.warning("canonical_load_error", path=str(p), error=str(exc))
        return docs
