"""fetch_raw handler for EDPB — Lambda step in ingest_edpb state machine.

Fetches EDPB (European Data Protection Board) Guidelines and Opinions (PDF)
and stores raw bytes in the S3 raw bucket.

EdpbSource.list_documents() takes no arguments; it returns a list of document
slugs from the EDPB listing page (e.g. "guidelines-012023").
EdpbSource._url_cache is populated during list_documents() so fetch() works.

Note: EDPB documents are PDFs per ADR 0011 exception.

Environment variables:
  RAW_BUCKET_NAME   : S3 bucket name for raw documents
  IDEMPOTENCY_TABLE : DynamoDB table name for idempotency
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

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

RAW_BUCKET = os.environ.get("RAW_BUCKET_NAME", "")


def _run_async(coro: Any) -> Any:
    """Run a coroutine in a new event loop (Lambda has no running loop)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _fetch_documents() -> list[tuple[str, bytes, str]]:
    """List and fetch EDPB documents.

    Returns list of (doc_id, raw_bytes, content_type) tuples.
    EdpbSource.list_documents() populates _url_cache so fetch() can resolve URLs.
    """
    from lex_agents_ingest.sources.edpb import EdpbSource

    source = EdpbSource()
    doc_ids = await source.list_documents()
    logger.info("edpb.fetch_raw.list_done", count=len(doc_ids))

    results: list[tuple[str, bytes, str]] = []
    for doc_id in doc_ids:
        try:
            raw = await source.fetch(doc_id)
            content_type = "application/pdf" if raw.content_type == "pdf" else "text/html"
            results.append((doc_id, raw.raw_bytes, content_type))
            logger.info("edpb.fetch_raw.fetched", doc_id=doc_id, bytes=len(raw.raw_bytes))
        except Exception as exc:
            logger.warning("edpb.fetch_raw.fetch_failed", doc_id=doc_id, error=str(exc))
    return results


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the EDPB FetchRaw stage."""
    evt = PipelineEvent.from_dict(event)
    logger.info("edpb.fetch_raw_start", run_date=evt.run_date)

    try:
        documents = _run_async(_fetch_documents())
    except Exception as exc:
        logger.error("edpb.fetch_raw.list_failed", error=str(exc))
        evt.status = "error"
        evt.error_message = str(exc)
        raise

    s3 = boto3.client("s3")
    stored_keys: list[str] = []
    failed_ids: list[str] = []

    for doc_id, raw_bytes, content_type in documents:
        safe_id = doc_id.replace("/", "_").replace(" ", "_")
        ext = "pdf" if "pdf" in content_type else "html"
        s3_key = f"edpb/{evt.run_date}/{safe_id}.{ext}"
        pipeline_doc_id = f"edpb/{evt.run_date}/{safe_id}"

        try:
            acquire_lock(pipeline_doc_id, "fetch_raw")
        except AlreadySucceeded as exc:
            logger.info("edpb.fetch_raw.cached", doc_id=pipeline_doc_id)
            stored_keys.append(exc.cached_output.get("raw_s3_key", ""))
            continue
        except StillRunning:
            logger.warning("edpb.fetch_raw.still_running", doc_id=pipeline_doc_id)
            continue

        try:
            s3.put_object(
                Bucket=RAW_BUCKET,
                Key=s3_key,
                Body=raw_bytes,
                ContentType=content_type,
                Metadata={
                    "source": "edpb",
                    "run_date": evt.run_date,
                    "doc_id": pipeline_doc_id,
                },
            )
            output_fields = {
                "doc_id": pipeline_doc_id,
                "raw_s3_key": f"s3://{RAW_BUCKET}/{s3_key}",
                "raw_content_type": content_type,
                "raw_byte_size": len(raw_bytes),
                "status": "success",
            }
            release_lock(pipeline_doc_id, "fetch_raw", output_fields)
            stored_keys.append(f"s3://{RAW_BUCKET}/{s3_key}")
            logger.info("edpb.fetch_raw.uploaded", doc_id=pipeline_doc_id, s3_key=s3_key)
        except Exception as exc:
            fail_lock(pipeline_doc_id, "fetch_raw", str(exc))
            failed_ids.append(pipeline_doc_id)
            logger.error("edpb.fetch_raw.upload_failed", doc_id=pipeline_doc_id, error=str(exc))

    last_doc_id = f"edpb/{evt.run_date}/batch"
    last_s3_key = stored_keys[-1] if stored_keys else ""

    output = {
        "doc_id": last_doc_id,
        "raw_s3_key": last_s3_key,
        "raw_content_type": "application/pdf",
        "raw_byte_size": len(stored_keys),
        "status": "success" if stored_keys else "error",
        "edpb_docs_stored": len(stored_keys),
        "edpb_docs_failed": len(failed_ids),
    }
    return PipelineEvent.from_dict({**event, **output}).to_dict()
