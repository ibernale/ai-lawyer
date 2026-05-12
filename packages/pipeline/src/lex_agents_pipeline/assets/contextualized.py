"""Contextualization assets — chunks → context-enriched chunks.

DataVersion = sha256 of contextualizer prompt file. When the prompt
changes, all downstream embedded/indexed assets re-materialize.
"""


import hashlib
import os
from pathlib import Path
from typing import Any

import structlog
from dagster import AssetExecutionContext, DataVersion, Output, asset

from lex_agents_pipeline.resources.clients import AnthropicResource

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_DATA_DIR = Path(os.environ.get("LEX_DATA_DIR", "data"))
_PROMPT_PATH = Path("docs/prompts/contextualizer_v1.md")


def _prompt_version() -> str:
    if _PROMPT_PATH.exists():
        return hashlib.sha256(_PROMPT_PATH.read_bytes()).hexdigest()[:8]
    return "noprompt"


def _contextualize_source(source_id: str, anthropic_resource: AnthropicResource) -> dict[str, Any]:
    chunks_dir = _DATA_DIR / "chunked" / source_id
    if not chunks_dir.exists():
        return {"chunks_enriched": 0, "chunks_skipped": 0}

    canon_dir = _DATA_DIR / "canonical" / source_id
    ctx_dir = _DATA_DIR / "contextualized" / source_id
    ctx_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # No API key — copy chunks as-is without context enrichment
        logger.warning("contextualize_skip_no_key", source=source_id)
        enriched = skipped = 0
        for chunk_path in chunks_dir.glob("*.jsonl"):
            out_path = ctx_dir / chunk_path.name
            if not out_path.exists():
                import shutil
                shutil.copy(chunk_path, out_path)
                skipped += 1
        return {"chunks_enriched": 0, "chunks_skipped": skipped}

    from anthropic import Anthropic
    from lex_agents_ingest.canonical import CanonicalDocument, Chunk
    from lex_agents_ingest.contextualizer import Contextualizer

    client = Anthropic(api_key=api_key)
    contextualizer = Contextualizer(client, cache_dir=_DATA_DIR / "contexts")

    enriched = skipped = 0
    for chunk_path in chunks_dir.glob("*.jsonl"):
        out_path = ctx_dir / chunk_path.name
        if out_path.exists():
            skipped += 1
            continue
        # Load canonical doc for context
        canon_path = canon_dir / f"{chunk_path.stem}.json"
        if not canon_path.exists():
            continue
        try:
            canonical = CanonicalDocument.model_validate_json(canon_path.read_text())
            chunks = [Chunk.model_validate_json(line) for line in chunk_path.read_text().splitlines() if line]
            enriched_chunks = contextualizer.enrich(canonical, chunks)
            with out_path.open("w") as fh:
                for c in enriched_chunks:
                    fh.write(c.model_dump_json() + "\n")
            enriched += len(enriched_chunks)
        except Exception as exc:
            logger.error("contextualize_error", source=source_id, path=str(chunk_path), error=str(exc))

    return {"chunks_enriched": enriched, "chunks_skipped": skipped}


def _make_contextualized_asset(src_id: str, group: str) -> Any:
    @asset(
        name=f"{src_id}_contextualized",
        group_name=group,
        compute_kind="contextualizer",
        deps=[f"{src_id}_chunked"],
        description=f"Context-enriched chunks for {src_id}",
        required_resource_keys={"anthropic"},
    )
    def _asset(context: AssetExecutionContext) -> Output[dict[str, Any]]:  # type: ignore[misc]
        anthropic_res: AnthropicResource = context.resources.anthropic  # type: ignore[attr-defined]
        report = _contextualize_source(src_id, anthropic_res)
        pv = _prompt_version()
        yield Output(
            value=report,
            data_version=DataVersion(pv),
            metadata={**report, "prompt_version": pv},
        )

    return _asset


boe_contextualized = _make_contextualized_asset("boe", "boe")
eurlex_contextualized = _make_contextualized_asset("eurlex", "eurlex")
aepd_contextualized = _make_contextualized_asset("aepd", "aepd")
edpb_contextualized = _make_contextualized_asset("edpb", "edpb")
bde_contextualized = _make_contextualized_asset("bde", "bde")
eba_contextualized = _make_contextualized_asset("eba", "eba")
esma_contextualized = _make_contextualized_asset("esma", "esma")
legislation_uk_contextualized = _make_contextualized_asset("legislation_uk", "legislation_uk")
fca_contextualized = _make_contextualized_asset("fca", "fca")

ALL_CONTEXTUALIZED_ASSETS = [
    boe_contextualized, eurlex_contextualized,
    aepd_contextualized, edpb_contextualized, bde_contextualized, eba_contextualized,
    esma_contextualized, legislation_uk_contextualized, fca_contextualized,
]
