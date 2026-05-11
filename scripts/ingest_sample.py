#!/usr/bin/env python3
"""Ingest sample documents using local fixture files (no network required).

Used by: make ingest-sample
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from anthropic import Anthropic
from lex_agents_ingest.canonical import RawDocument
from lex_agents_ingest.chunker import LegalChunker
from lex_agents_ingest.contextualizer import Contextualizer
from lex_agents_ingest.embedder import BgeM3Embedder
from lex_agents_ingest.indexer import QdrantIndexer
from lex_agents_ingest.pipeline import IngestPipeline
from lex_agents_ingest.sources.boe import BoeSource
from lex_agents_ingest.sources.eurlex import EurlexSource
from lex_agents_ingest.storage import IngestStorage
from qdrant_client import QdrantClient

FIXTURES = Path(__file__).parent.parent / "packages" / "ingest" / "tests" / "fixtures"
DATA_DIR = Path("data")

SAMPLE_BOE = ["BOE-A-2014-6732", "BOE-A-2015-1510"]
SAMPLE_EURLEX = ["32013R0575", "32013L0036"]


def _make_mock_source(source_name: str, ids: list[str], fixture_dir: Path) -> MagicMock:
    src = MagicMock()
    src.source_id = source_name
    src._rate_limiter = MagicMock()
    src._rate_limiter.acquire = AsyncMock()

    fixture_map = {
        doc_id: (fixture_dir / f"{doc_id}.xml").read_bytes()
        for doc_id in ids
        if (fixture_dir / f"{doc_id}.xml").exists()
    }

    async def list_docs() -> list[str]:
        return [d for d in ids if d in fixture_map]

    async def fetch(doc_id: str) -> RawDocument:
        return RawDocument(
            source=source_name,
            source_id=doc_id,
            raw_url=f"fixture://{source_name}/{doc_id}.xml",
            content_type="xml",
            raw_bytes=fixture_map[doc_id],
        )

    src.list_documents = list_docs
    src.fetch = fetch
    return src


async def _run_source(
    source_name: str,
    ids: list[str],
    fixture_dir: Path,
    parse_fn: object,
    anthropic_key: str,
) -> None:
    mock_src = _make_mock_source(source_name, ids, fixture_dir)
    mock_src.parse_to_canonical = parse_fn

    storage = IngestStorage(base_dir=DATA_DIR)
    chunker = LegalChunker(max_tokens=1024)

    if anthropic_key:
        anthropic = Anthropic(api_key=anthropic_key)
        contextualizer = Contextualizer(anthropic, cache_dir=DATA_DIR / "contexts")
    else:
        print(f"  [!] ANTHROPIC_API_KEY not set — skipping contextualisation for {source_name}")
        ctx_mock = MagicMock()
        ctx_mock.enrich = lambda doc, chunks: chunks
        contextualizer = ctx_mock  # type: ignore[assignment]

    embedder = BgeM3Embedder()
    qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    indexer = QdrantIndexer(qdrant)

    pipeline = IngestPipeline(mock_src, chunker, contextualizer, embedder, indexer, storage)
    report = await pipeline.run()

    print(f"  {source_name}: ok={report.docs_ok} failed={report.docs_failed} chunks={report.chunks_indexed}")
    for f in report.failures:
        print(f"    FAILURE {f.doc_id}: {f.error}")


async def main() -> None:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    print("=== ingest-sample (fixture-based) ===")

    boe = BoeSource()
    await _run_source("boe", SAMPLE_BOE, FIXTURES / "boe", boe.parse_to_canonical, anthropic_key)

    eurlex = EurlexSource()
    await _run_source("eurlex", SAMPLE_EURLEX, FIXTURES / "eurlex", eurlex.parse_to_canonical, anthropic_key)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
