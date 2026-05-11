"""Embedding assets — contextualized chunks → dense vectors JSONL.

DataVersion = embedder model name. When the model changes, all embedded
and indexed assets re-materialize automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import structlog
from dagster import AssetExecutionContext, DataVersion, Output, asset

from lex_agents_pipeline.resources.clients import EmbedderResource

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("LEX_DATA_DIR", "data"))


def _embed_source(source_id: str, embedder_resource: EmbedderResource) -> dict[str, Any]:
    ctx_dir = _DATA_DIR / "contextualized" / source_id
    if not ctx_dir.exists():
        return {"chunks_embedded": 0, "model": embedder_resource.model_name}

    emb_dir = _DATA_DIR / "embedded" / source_id
    emb_dir.mkdir(parents=True, exist_ok=True)

    embedder = embedder_resource.get_embedder()  # type: ignore[attr-defined]
    from lex_agents_ingest.canonical import Chunk

    total = 0
    for ctx_path in ctx_dir.glob("*.jsonl"):
        out_path = emb_dir / ctx_path.name.replace(".jsonl", ".emb.jsonl")
        try:
            chunks = [Chunk.model_validate_json(line) for line in ctx_path.read_text().splitlines() if line]
            texts = [f"{c.context_text}\n\n{c.text}" if c.context_text else c.text for c in chunks]
            embeddings = embedder.embed_batch(texts)  # type: ignore[attr-defined]
            with out_path.open("w") as fh:
                for chunk, emb in zip(chunks, embeddings):
                    record = {
                        "chunk_id": chunk.chunk_id,
                        "dense": emb.dense,
                        "sparse": emb.sparse,
                    }
                    fh.write(json.dumps(record) + "\n")
            total += len(chunks)
        except Exception as exc:
            logger.error("embed_error", source=source_id, path=str(ctx_path), error=str(exc))

    return {"chunks_embedded": total, "model": embedder_resource.model_name}


def _make_embedded_asset(src_id: str, group: str) -> Any:
    @asset(
        name=f"{src_id}_embedded",
        group_name=group,
        compute_kind="embedder",
        deps=[f"{src_id}_contextualized"],
        description=f"Dense vectors for {src_id}",
        required_resource_keys={"embedder"},
    )
    def _asset(context: AssetExecutionContext) -> Output[dict[str, Any]]:  # type: ignore[misc]
        embedder_res: EmbedderResource = context.resources.embedder  # type: ignore[attr-defined]
        report = _embed_source(src_id, embedder_res)
        # DataVersion = model name hash — change model → invalidate downstream
        model_hash = hashlib.sha256(embedder_res.model_name.encode()).hexdigest()[:8]
        yield Output(
            value=report,
            data_version=DataVersion(model_hash),
            metadata=report,
        )

    return _asset


boe_embedded = _make_embedded_asset("boe", "boe")
eurlex_embedded = _make_embedded_asset("eurlex", "eurlex")
aepd_embedded = _make_embedded_asset("aepd", "aepd")
edpb_embedded = _make_embedded_asset("edpb", "edpb")
bde_embedded = _make_embedded_asset("bde", "bde")
eba_embedded = _make_embedded_asset("eba", "eba")
esma_embedded = _make_embedded_asset("esma", "esma")
legislation_uk_embedded = _make_embedded_asset("legislation_uk", "legislation_uk")
fca_embedded = _make_embedded_asset("fca", "fca")

ALL_EMBEDDED_ASSETS = [
    boe_embedded, eurlex_embedded,
    aepd_embedded, edpb_embedded, bde_embedded, eba_embedded, esma_embedded,
    legislation_uk_embedded, fca_embedded,
]
