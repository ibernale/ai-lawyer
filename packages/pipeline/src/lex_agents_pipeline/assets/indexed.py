"""Indexing assets — embedded vectors → Qdrant upsert.

The domain= payload field is set here per source (ADR 0010: single
collection, domain filter for per-branch retrieval).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog
from dagster import AssetExecutionContext, AssetCheckResult, AssetCheckSpec, DataVersion, Output, asset, asset_check

from lex_agents_pipeline.resources.clients import QdrantResource

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("LEX_DATA_DIR", "data"))

# Maps source_id → domain tag for Qdrant payload (ADR 0010)
_SOURCE_DOMAIN: dict[str, str] = {
    "boe": "regulatorio_bancario",
    "eurlex": "regulatorio_bancario",
    "aepd": "datos_personales",
    "edpb": "datos_personales",
    "bde": "regulatorio_bancario",
    "eba": "regulatorio_bancario",
    "esma": "mercantil",
    "legislation_uk": "regulatorio_bancario",
    "fca": "regulatorio_bancario",
}


def _index_source(source_id: str, qdrant_resource: QdrantResource) -> dict[str, Any]:
    emb_dir = _DATA_DIR / "embedded" / source_id
    if not emb_dir.exists():
        return {"upserted": 0, "skipped": 0}

    ctx_dir = _DATA_DIR / "contextualized" / source_id
    canon_dir = _DATA_DIR / "canonical" / source_id

    qdrant_client = qdrant_resource.get_client()  # type: ignore[attr-defined]
    collection = qdrant_resource.collection_name
    domain = _SOURCE_DOMAIN.get(source_id, source_id)

    from lex_agents_ingest.canonical import Chunk
    from lex_agents_ingest.embedder import EmbeddingResult
    from lex_agents_ingest.indexer import QdrantIndexer

    indexer = QdrantIndexer(qdrant_client, collection_name=collection)
    indexer.ensure_collection()

    upserted = skipped = 0
    for emb_path in emb_dir.glob("*.emb.jsonl"):
        stem = emb_path.name.replace(".emb.jsonl", "")
        ctx_path = ctx_dir / f"{stem}.jsonl"
        if not ctx_path.exists():
            continue
        try:
            chunks = [Chunk.model_validate_json(line) for line in ctx_path.read_text().splitlines() if line]
            emb_records = [json.loads(line) for line in emb_path.read_text().splitlines() if line]

            # Attach domain to each chunk payload
            for chunk in chunks:
                chunk_dict = chunk.model_dump()
                chunk_dict["domain"] = domain

            embeddings = [
                EmbeddingResult(
                    dense=r["dense"],
                    sparse={int(k): v for k, v in r.get("sparse", {}).items()},
                )
                for r in emb_records
            ]

            if len(chunks) != len(embeddings):
                logger.warning("chunk_emb_mismatch", source=source_id, stem=stem)
                continue

            # Inject domain into chunk payloads via model copy
            patched_chunks = []
            for c in chunks:
                data = c.model_dump()
                data["domain"] = domain
                patched_chunks.append(Chunk.model_validate(data))

            result = indexer.upsert_chunks(patched_chunks, embeddings)
            upserted += result.inserted + result.updated
        except Exception as exc:
            logger.error("index_error", source=source_id, stem=stem, error=str(exc))

    return {"upserted": upserted, "skipped": skipped, "collection": collection, "domain": domain}


def _make_indexed_asset(src_id: str, group: str) -> Any:
    @asset(
        name=f"{src_id}_indexed",
        group_name=group,
        compute_kind="indexer",
        deps=[f"{src_id}_embedded"],
        description=f"Qdrant index for {src_id} (domain={_SOURCE_DOMAIN.get(src_id, src_id)})",
        required_resource_keys={"qdrant"},
    )
    def _asset(context: AssetExecutionContext) -> Output[dict[str, Any]]:  # type: ignore[misc]
        qdrant_res: QdrantResource = context.resources.qdrant  # type: ignore[attr-defined]
        report = _index_source(src_id, qdrant_res)
        yield Output(
            value=report,
            metadata=report,
        )

    return _asset


boe_indexed = _make_indexed_asset("boe", "boe")
eurlex_indexed = _make_indexed_asset("eurlex", "eurlex")
aepd_indexed = _make_indexed_asset("aepd", "aepd")
edpb_indexed = _make_indexed_asset("edpb", "edpb")
bde_indexed = _make_indexed_asset("bde", "bde")
eba_indexed = _make_indexed_asset("eba", "eba")
esma_indexed = _make_indexed_asset("esma", "esma")
legislation_uk_indexed = _make_indexed_asset("legislation_uk", "legislation_uk")
fca_indexed = _make_indexed_asset("fca", "fca")


@asset_check(asset=boe_indexed, name="boe_qdrant_collection_exists")
def boe_qdrant_collection_exists(context: AssetExecutionContext) -> AssetCheckResult:
    """Verify the Qdrant collection was created and has points."""
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=qdrant_url)
        info = client.get_collection("lex_legal_docs")
        count = info.points_count or 0
        return AssetCheckResult(passed=count > 0, metadata={"points_count": count})
    except Exception as exc:
        return AssetCheckResult(passed=False, metadata={"error": str(exc)})


ALL_INDEXED_ASSETS = [
    boe_indexed, eurlex_indexed,
    aepd_indexed, edpb_indexed, bde_indexed, eba_indexed, esma_indexed,
    legislation_uk_indexed, fca_indexed,
]
ALL_INDEXED_CHECKS = [boe_qdrant_collection_exists]
