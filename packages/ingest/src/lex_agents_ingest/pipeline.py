"""End-to-end ingestion pipeline: fetch → parse → chunk → contextualise → embed → index."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from lex_agents_ingest.base import Source
from lex_agents_ingest.chunker import LegalChunker
from lex_agents_ingest.contextualizer import Contextualizer
from lex_agents_ingest.embedder import BgeM3Embedder
from lex_agents_ingest.indexer import QdrantIndexer
from lex_agents_ingest.storage import IngestStorage

logger: structlog.BoundLogger = structlog.get_logger(__name__)


@dataclass
class FailureDetail:
    doc_id: str
    stage: str
    error: str


@dataclass
class PipelineReport:
    docs_attempted: int = 0
    docs_ok: int = 0
    docs_failed: int = 0
    chunks_indexed: int = 0
    failures: list[FailureDetail] = field(default_factory=list)


class IngestPipeline:
    """Orchestrates the full ingestion flow for one Source.

    Never aborts mid-run: errors are caught per-document and accumulated
    in PipelineReport.failures.
    """

    def __init__(
        self,
        source: Source,
        chunker: LegalChunker,
        contextualizer: Contextualizer,
        embedder: BgeM3Embedder,
        indexer: QdrantIndexer,
        storage: IngestStorage,
    ) -> None:
        self._source = source
        self._chunker = chunker
        self._contextualizer = contextualizer
        self._embedder = embedder
        self._indexer = indexer
        self._storage = storage

    async def run(self, doc_ids: list[str] | None = None) -> PipelineReport:
        """Run the pipeline.

        If *doc_ids* is None, fetches the full document list from the source.
        """
        ids = doc_ids or await self._source.list_documents()
        report = PipelineReport(docs_attempted=len(ids))
        self._indexer.ensure_collection()

        for doc_id in ids:
            try:
                chunks_indexed = await self._process_one(doc_id)
                report.docs_ok += 1
                report.chunks_indexed += chunks_indexed
            except Exception as exc:
                report.docs_failed += 1
                report.failures.append(
                    FailureDetail(doc_id=doc_id, stage="unknown", error=str(exc))
                )
                logger.error("pipeline_doc_failed", doc_id=doc_id, error=str(exc))

        logger.info(
            "pipeline_complete",
            source=self._source.source_id,
            docs_ok=report.docs_ok,
            docs_failed=report.docs_failed,
            chunks_indexed=report.chunks_indexed,
        )
        return report

    async def _process_one(self, doc_id: str) -> int:
        """Process one document. Returns the number of chunks indexed."""
        # 1. Fetch
        raw = await self._source.fetch(doc_id)
        self._storage.write_raw(raw)

        # 2. Parse
        canonical = self._source.parse_to_canonical(raw)
        result = self._storage.write_canonical(canonical)
        if result.skipped:
            logger.info("doc_unchanged", doc_id=doc_id)

        # 3. Chunk
        chunks = self._chunker.chunk(canonical)
        if not chunks:
            logger.warning("no_chunks", doc_id=doc_id)
            return 0

        # 4. Contextualise
        chunks = self._contextualizer.enrich(canonical, chunks)

        # 5. Embed — use context_text prepended to text for retrieval
        texts = [f"{c.context_text}\n\n{c.text}" if c.context_text else c.text for c in chunks]
        embeddings = self._embedder.embed_batch(texts)

        # 6. Index
        upsert = self._indexer.upsert_chunks(chunks, embeddings)
        return upsert.inserted + upsert.updated
