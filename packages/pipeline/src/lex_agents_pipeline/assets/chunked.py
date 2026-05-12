"""Chunking assets — CanonicalDocument JSON → Chunk list JSON.

DataVersion = hash of LegalChunker config + canonical checksum.
When max_tokens or overlap changes, all downstream assets re-materialize.
"""


import hashlib
import os
from pathlib import Path
from typing import Any

import structlog
from dagster import AssetExecutionContext, DataVersion, Output, asset
from lex_agents_ingest.chunker import LegalChunker
from lex_agents_ingest.storage import IngestStorage

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("LEX_DATA_DIR", "data"))

# Chunker config — changing these invalidates all downstream assets
_CHUNKER_MAX_TOKENS = int(os.environ.get("LEX_CHUNKER_MAX_TOKENS", "1024"))
_CHUNKER_CONFIG_HASH = hashlib.sha256(
    f"max_tokens={_CHUNKER_MAX_TOKENS}".encode()
).hexdigest()[:8]


def _chunk_source(source_id: str) -> dict[str, Any]:
    storage = IngestStorage(base_dir=_DATA_DIR)
    canon_dir = _DATA_DIR / "canonical" / source_id
    if not canon_dir.exists():
        return {"chunks_written": 0, "docs_processed": 0}

    chunker = LegalChunker(max_tokens=_CHUNKER_MAX_TOKENS)
    chunks_dir = _DATA_DIR / "chunked" / source_id
    chunks_dir.mkdir(parents=True, exist_ok=True)

    total_chunks = docs = 0
    for canon_path in canon_dir.glob("*.json"):
        try:
            from lex_agents_ingest.canonical import CanonicalDocument
            canonical = CanonicalDocument.model_validate_json(canon_path.read_text())
            chunks = chunker.chunk(canonical)
            out_path = chunks_dir / f"{canon_path.stem}.jsonl"
            with out_path.open("w") as fh:
                for c in chunks:
                    fh.write(c.model_dump_json() + "\n")
            total_chunks += len(chunks)
            docs += 1
        except Exception as exc:
            logger.error("chunk_error", source=source_id, path=str(canon_path), error=str(exc))

    return {"chunks_written": total_chunks, "docs_processed": docs}


def _chunks_version(source_id: str) -> str:
    chunks_dir = _DATA_DIR / "chunked" / source_id
    if not chunks_dir.exists():
        return "empty"
    h = hashlib.sha256()
    h.update(_CHUNKER_CONFIG_HASH.encode())
    for p in sorted(chunks_dir.glob("*.jsonl")):
        h.update(p.stat().st_mtime_ns.to_bytes(8, "big"))
    return h.hexdigest()[:16]


def _make_chunked_asset(src_id: str, group: str) -> Any:
    @asset(
        name=f"{src_id}_chunked",
        group_name=group,
        compute_kind="chunker",
        deps=[f"{src_id}_canonical"],
        description=f"Legal chunks for {src_id} (max_tokens={_CHUNKER_MAX_TOKENS})",
        metadata={"chunker_config_hash": _CHUNKER_CONFIG_HASH},
    )
    def _asset(context: AssetExecutionContext) -> Output[dict[str, Any]]:  # type: ignore[misc]
        report = _chunk_source(src_id)
        version = _chunks_version(src_id)
        yield Output(
            value=report,
            data_version=DataVersion(f"{_CHUNKER_CONFIG_HASH}:{version}"),
            metadata=report,
        )

    return _asset


boe_chunked = _make_chunked_asset("boe", "boe")
eurlex_chunked = _make_chunked_asset("eurlex", "eurlex")
aepd_chunked = _make_chunked_asset("aepd", "aepd")
edpb_chunked = _make_chunked_asset("edpb", "edpb")
bde_chunked = _make_chunked_asset("bde", "bde")
eba_chunked = _make_chunked_asset("eba", "eba")
esma_chunked = _make_chunked_asset("esma", "esma")
legislation_uk_chunked = _make_chunked_asset("legislation_uk", "legislation_uk")
fca_chunked = _make_chunked_asset("fca", "fca")

ALL_CHUNKED_ASSETS = [
    boe_chunked, eurlex_chunked,
    aepd_chunked, edpb_chunked, bde_chunked, eba_chunked, esma_chunked,
    legislation_uk_chunked, fca_chunked,
]
