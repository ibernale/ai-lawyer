"""Lambda handler — ChunkDocument stage (ADR 0047).

Reads canonical JSON from S3, applies the existing chunking logic from
`lex_agents_rag.chunker`, and writes a JSONL file (one chunk per line)
back to the canonical S3 bucket.

Input  (PipelineEvent fields used):
  doc_id           : set by FetchRaw
  source           : "boe" | "eur_lex"
  canonical_s3_key : set by ParseCanonical

Output (new fields added to PipelineEvent):
  chunks_s3_key : "s3://<canonical-bucket>/<doc_id>.chunks.jsonl"
  chunks_count  : number of chunks produced

Environment variables:
  CANONICAL_BUCKET_NAME : S3 bucket for canonical + chunk docs
  IDEMPOTENCY_TABLE     : DynamoDB table name
  CHUNK_SIZE            : target chunk token size (default 512)
  CHUNK_OVERLAP         : overlap tokens between chunks (default 64)
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import boto3
import structlog

from lex_pipeline_aws.idempotency import (
    AlreadySucceeded,
    StillRunning,
    acquire_lock,
    fail_lock,
    release_lock,
)
from lex_pipeline_aws.types import PipelineEvent

logger: structlog.BoundLogger = structlog.get_logger(__name__)

CANONICAL_BUCKET = os.environ.get("CANONICAL_BUCKET_NAME", "")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "64"))


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

def _simple_chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Naive word-boundary chunker — replaced by lex_agents_rag.chunker in Fase 9.3.

    Splits on whitespace into token-approximated windows of `chunk_size` words
    with `overlap` word overlap.
    """
    words = text.split()
    if not words:
        return []
    chunks = []
    step = max(1, chunk_size - overlap)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
        if i + chunk_size >= len(words):
            break
    return chunks


def _chunk_canonical(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a canonical document dict into a list of chunk dicts."""
    chunks: list[dict[str, Any]] = []
    doc_id = canonical.get("doc_id", "")
    source = canonical.get("source", "")
    doc_date = canonical.get("doc_date", "")
    doc_type = canonical.get("doc_type", "")
    doc_title = canonical.get("doc_title", "")

    # For BOE sumario: chunk each item title + context
    items = canonical.get("items", [])
    if items:
        for idx, item in enumerate(items):
            text = f"{doc_title}\n{item.get('title', '')}".strip()
            if not text:
                continue
            text_chunks = _simple_chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
            for chunk_idx, chunk_text in enumerate(text_chunks):
                chunks.append({
                    "chunk_id": f"{doc_id}#item{idx}#chunk{chunk_idx}",
                    "doc_id": doc_id,
                    "source": source,
                    "doc_date": doc_date,
                    "doc_type": doc_type,
                    "doc_title": doc_title,
                    "section": item.get("title", ""),
                    "text": chunk_text,
                    "item_id": item.get("id", ""),
                    "url_xml": item.get("url_xml", ""),
                    "chunk_index": chunk_idx,
                })
    else:
        # Generic: chunk doc_title as a single chunk
        chunks.append({
            "chunk_id": f"{doc_id}#chunk0",
            "doc_id": doc_id,
            "source": source,
            "doc_date": doc_date,
            "doc_type": doc_type,
            "doc_title": doc_title,
            "section": "",
            "text": doc_title,
            "chunk_index": 0,
        })

    return chunks


def _read_s3_json(s3_uri: str) -> dict[str, Any]:
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(resp["Body"].read())


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the ChunkDocument stage."""
    evt = PipelineEvent.from_dict(event)
    logger.info("chunk_document_start", doc_id=evt.doc_id)

    try:
        try:
            acquire_lock(evt.doc_id, "chunk_document")
        except AlreadySucceeded as exc:
            logger.info("chunk_document_cached", doc_id=evt.doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise

        # Read canonical JSON
        canonical = _read_s3_json(evt.canonical_s3_key)

        # Chunk
        chunks = _chunk_canonical(canonical)
        logger.info("chunk_document_chunked", doc_id=evt.doc_id, chunks=len(chunks))

        # Write JSONL to S3
        year = evt.run_date[:4]
        s3_key = f"{evt.source}/{year}/{evt.doc_id.replace('/', '_')}.chunks.jsonl"
        jsonl_bytes = "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks).encode("utf-8")

        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=CANONICAL_BUCKET,
            Key=s3_key,
            Body=jsonl_bytes,
            ContentType="application/x-ndjson",
            Metadata={"doc_id": evt.doc_id, "chunks_count": str(len(chunks))},
        )

        output_fields = {
            "chunks_s3_key": f"s3://{CANONICAL_BUCKET}/{s3_key}",
            "chunks_count": len(chunks),
            "status": "success",
        }
        release_lock(evt.doc_id, "chunk_document", output_fields)
        return PipelineEvent.from_dict({**event, **output_fields}).to_dict()

    except (AlreadySucceeded, StillRunning):
        raise
    except Exception as exc:
        logger.error("chunk_document_error", error=str(exc), doc_id=evt.doc_id)
        fail_lock(evt.doc_id, "chunk_document", str(exc))
        raise
