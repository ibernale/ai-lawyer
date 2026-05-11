#!/usr/bin/env python3
"""Ingest sample documents from live BOE and EUR-Lex APIs.

Requires:
    - ANTHROPIC_API_KEY (for contextualisation)
    - Qdrant running at QDRANT_URL (default: http://localhost:6333)
    - Network access to boe.es and publications.europa.eu

Used by: make ingest-real
"""

from __future__ import annotations

import asyncio
import os

import httpx
from anthropic import Anthropic
from lex_agents_ingest.chunker import LegalChunker
from lex_agents_ingest.contextualizer import Contextualizer
from lex_agents_ingest.embedder import BgeM3Embedder
from lex_agents_ingest.indexer import QdrantIndexer
from lex_agents_ingest.pipeline import IngestPipeline
from lex_agents_ingest.sources.boe import BoeSource
from lex_agents_ingest.sources.eurlex import EurlexSource
from lex_agents_ingest.storage import IngestStorage
from qdrant_client import QdrantClient


async def _run(source: object, anthropic_key: str) -> None:
    from lex_agents_ingest.base import Source
    assert isinstance(source, Source)
    storage = IngestStorage(base_dir="data")
    chunker = LegalChunker(max_tokens=1024)
    anthropic = Anthropic(api_key=anthropic_key)
    contextualizer = Contextualizer(anthropic, cache_dir="data/contexts")
    embedder = BgeM3Embedder()
    qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    indexer = QdrantIndexer(qdrant)

    pipeline = IngestPipeline(source, chunker, contextualizer, embedder, indexer, storage)
    report = await pipeline.run()
    print(f"  {source.source_id}: ok={report.docs_ok} failed={report.docs_failed} chunks={report.chunks_indexed}")
    for f in report.failures:
        print(f"    FAILURE {f.doc_id}: {f.error}")


async def main() -> None:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        raise SystemExit(1)

    print("=== ingest-real (live APIs) ===")
    async with httpx.AsyncClient(timeout=30) as http:
        await _run(BoeSource(http_client=http), key)
        await _run(EurlexSource(http_client=http), key)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
