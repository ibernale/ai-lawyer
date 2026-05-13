#!/usr/bin/env python3
"""Ingest sample documents from data/raw/ into Qdrant (no network required).

Reads raw XML files already present in data/raw/boe/ and data/raw/eurlex/,
parses them, chunks, contextualises (if ANTHROPIC_API_KEY is set), embeds,
and indexes into Qdrant.

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

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"

# Fall back to test fixtures if data/raw/ not populated
FIXTURES = Path(__file__).parent.parent / "packages" / "ingest" / "tests" / "fixtures"


def _make_source_from_dir(
    source_name: str,
    raw_dir: Path,
    parse_fn: object,
    ext: str = "xml",
) -> MagicMock:
    """Create a mock source that reads from a local directory."""
    src = MagicMock()
    src.source_id = source_name
    src._rate_limiter = MagicMock()
    src._rate_limiter.acquire = AsyncMock()
    src.parse_to_canonical = parse_fn

    # Gather all documents in the directory
    doc_files = {p.stem: p for p in raw_dir.glob(f"*.{ext}")} if raw_dir.exists() else {}

    if not doc_files:
        # Fall back to fixtures
        fixture_dir = FIXTURES / source_name
        doc_files = {p.stem: p for p in fixture_dir.glob(f"*.{ext}")} if fixture_dir.exists() else {}
        if doc_files:
            print(f"  [{source_name}] using test fixtures (data/raw/{source_name}/ is empty)")

    async def list_docs() -> list[str]:
        return list(doc_files.keys())

    async def fetch(doc_id: str) -> RawDocument:
        path = doc_files[doc_id]
        return RawDocument(
            source=source_name,
            source_id=doc_id,
            raw_url=f"file://{path}",
            content_type=ext,  # type: ignore[arg-type]
            raw_bytes=path.read_bytes(),
        )

    src.list_documents = list_docs
    src.fetch = fetch
    return src


async def _run_source(
    source_name: str,
    raw_dir: Path,
    parse_fn: object,
    anthropic_key: str,
    qdrant_url: str,
) -> None:
    mock_src = _make_source_from_dir(source_name, raw_dir, parse_fn)

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
    qdrant = QdrantClient(url=qdrant_url)
    indexer = QdrantIndexer(qdrant)

    pipeline = IngestPipeline(mock_src, chunker, contextualizer, embedder, indexer, storage)
    report = await pipeline.run()

    print(f"  {source_name}: ok={report.docs_ok} failed={report.docs_failed} chunks={report.chunks_indexed}")
    for f in report.failures:
        print(f"    FAILURE {f.doc_id}: {f.error}")


async def main() -> None:
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    print(f"=== ingest-sample === qdrant={qdrant_url}")

    boe = BoeSource()
    await _run_source("boe", RAW_DIR / "boe", boe.parse_to_canonical, anthropic_key, qdrant_url)

    eurlex = EurlexSource()
    await _run_source("eurlex", RAW_DIR / "eurlex", eurlex.parse_to_canonical, anthropic_key, qdrant_url)

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
