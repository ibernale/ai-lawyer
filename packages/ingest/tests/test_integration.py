"""Integration tests — require Qdrant running. Skip in CI.

Run with: pytest -m integration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.integration
class TestFullPipelineBoeFixture:
    def test_full_pipeline_boe_fixture(self) -> None:
        import asyncio
        import tempfile

        from lex_agents_ingest.chunker import LegalChunker
        from lex_agents_ingest.contextualizer import Contextualizer
        from lex_agents_ingest.indexer import QdrantIndexer
        from lex_agents_ingest.pipeline import IngestPipeline
        from lex_agents_ingest.sources.boe import BoeSource
        from lex_agents_ingest.storage import IngestStorage
        from qdrant_client import QdrantClient

        boe_xml = (FIXTURE_DIR / "boe" / "BOE-A-2014-6732.xml").read_bytes()
        raw_mock = MagicMock()
        raw_mock.source_id = "BOE-A-2014-6732"
        raw_mock.source = "boe"
        raw_mock.content_type = "xml"
        raw_mock.raw_bytes = boe_xml
        import hashlib
        raw_mock.checksum = hashlib.sha256(boe_xml).hexdigest()

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = IngestStorage(base_dir=tmpdir)
            chunker = LegalChunker(max_tokens=512)

            # Mock Anthropic for contextualizer
            anthropic_mock = MagicMock()
            ctx_content = MagicMock()
            ctx_content.text = "Artículo que regula la autorización bancaria."
            ctx_resp = MagicMock()
            ctx_resp.content = [ctx_content]
            ctx_resp.usage = MagicMock(cache_read_input_tokens=0)
            anthropic_mock.messages.create.return_value = ctx_resp
            contextualizer = Contextualizer(anthropic_mock, cache_dir=tmpdir + "/ctx")

            # Mock embedder — return one EmbeddingResult per text in the batch
            embedder = MagicMock()
            from lex_agents_ingest.embedder import EmbeddingResult
            embedder.embed_batch.side_effect = lambda texts: [
                EmbeddingResult(dense=[0.1] * 1024, sparse={1: 0.5})
                for _ in texts
            ]

            # Real Qdrant
            qdrant = QdrantClient(url="http://localhost:6333")
            indexer = QdrantIndexer(qdrant, collection_name="test_integration_boe")

            # Mock source
            source = MagicMock()
            source.source_id = "boe"
            from lex_agents_ingest.canonical import RawDocument
            async def mock_list() -> list[str]:
                return ["BOE-A-2014-6732"]
            async def mock_fetch(doc_id: str) -> RawDocument:
                return RawDocument(
                    source="boe",
                    source_id=doc_id,
                    raw_url="https://boe.es",
                    content_type="xml",
                    raw_bytes=boe_xml,
                )
            from lex_agents_ingest.sources.boe import BoeSource
            boe = BoeSource()
            source.list_documents = mock_list
            source.fetch = mock_fetch
            source.parse_to_canonical = boe.parse_to_canonical

            pipeline = IngestPipeline(source, chunker, contextualizer, embedder, indexer, storage)

            try:
                report = asyncio.run(pipeline.run())
                assert report.docs_ok >= 1
                assert report.chunks_indexed >= 1
                assert report.docs_failed == 0
            finally:
                try:
                    qdrant.delete_collection("test_integration_boe")
                except Exception:
                    pass


@pytest.mark.integration
class TestSearchRetrievesIngestedChunks:
    def test_search_retrieves_ingested_chunks(self) -> None:
        """Smoke test: index a chunk and retrieve it via hybrid search."""
        from datetime import date

        from lex_agents_ingest.canonical import Chunk
        from lex_agents_ingest.embedder import EmbeddingResult
        from lex_agents_ingest.indexer import QdrantIndexer
        from lex_agents_rag.retriever import HybridRetriever
        from qdrant_client import QdrantClient

        qdrant = QdrantClient(url="http://localhost:6333")
        indexer = QdrantIndexer(qdrant, collection_name="test_search_chunks")
        indexer.ensure_collection()

        chunk = Chunk(
            chunk_id="abc123def456789a",
            jurisdiction="EU",
            source="EURLEX",
            source_id="32013R0575",
            hierarchy_path="CRR > Art. 92",
            publication_date=date(2013, 6, 27),
            text="La ratio de capital de nivel 1 ordinario es del 4,5 por ciento.",
        )
        emb = EmbeddingResult(dense=[0.1] * 1024, sparse={1: 0.5, 2: 0.3})
        indexer.upsert_chunks([chunk], [emb])

        embedder = MagicMock()
        embedder.embed_batch.return_value = [EmbeddingResult(dense=[0.1] * 1024, sparse={1: 0.5})]
        retriever = HybridRetriever(qdrant, embedder, collection="test_search_chunks")
        results = retriever.search("requisitos capital CET1", k_rrf=5)

        assert len(results) >= 1
        assert any(r.chunk_id == chunk.chunk_id for r in results)

        try:
            qdrant.delete_collection("test_search_chunks")
        except Exception:
            pass
