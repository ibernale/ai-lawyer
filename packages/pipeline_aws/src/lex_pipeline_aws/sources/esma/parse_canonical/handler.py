"""parse_canonical handler for ESMA — Lambda step in ingest_esma state machine.

Reads a raw ESMA Q&A HTML document from S3, parses it into canonical JSON
using EsmaSource.parse_to_canonical(), and stores in the canonical S3 bucket.

Environment variables:
  CANONICAL_BUCKET_NAME : S3 bucket for canonical docs
  IDEMPOTENCY_TABLE     : DynamoDB table name
"""

from __future__ import annotations

import json
import os
from datetime import datetime
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


def _read_s3_object(s3_uri: str) -> bytes:
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the ESMA ParseCanonical stage."""
    from lex_agents_ingest.canonical import RawDocument
    from lex_agents_ingest.sources.esma import EsmaSource

    evt = PipelineEvent.from_dict(event)
    logger.info("esma.parse_canonical_start", doc_id=evt.doc_id)

    try:
        try:
            acquire_lock(evt.doc_id, "parse_canonical")
        except AlreadySucceeded as exc:
            logger.info("esma.parse_canonical_cached", doc_id=evt.doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise

        raw_bytes = _read_s3_object(evt.raw_s3_key)

        source_id = evt.doc_id.split("/")[-1]
        if source_id == "batch":
            raise ValueError("Batch doc_id 'batch' cannot be parsed directly")

        raw_doc = RawDocument(
            source="esma",
            source_id=source_id,
            raw_url=evt.raw_s3_key,
            content_type="html",
            raw_bytes=raw_bytes,
            fetched_at=datetime.utcnow(),
        )

        source = EsmaSource.__new__(EsmaSource)
        canonical = source.parse_to_canonical(raw_doc)

        doc_date = canonical.publication_date.isoformat() if canonical.publication_date else evt.run_date
        canonical_dict = {
            "source": canonical.source,
            "doc_id": evt.doc_id,
            "title": canonical.title,
            "date": doc_date,
            "url": canonical.raw_url,
            "content_text": canonical.full_text,
            "document_type": canonical.type,
            "jurisdiction": canonical.jurisdiction,
            "domain": canonical.domain,
            "run_date": evt.run_date,
            "pipeline_version": evt.pipeline_version,
            "extra": canonical.extra or {},
        }

        safe_doc_id = evt.doc_id.replace("/", "_")
        s3_key = f"esma/{evt.run_date}/{safe_doc_id}.json"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=CANONICAL_BUCKET,
            Key=s3_key,
            Body=json.dumps(canonical_dict, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
            Metadata={"doc_id": evt.doc_id, "source": "esma"},
        )

        logger.info("esma.parse_canonical_done", doc_id=evt.doc_id, s3_key=s3_key)

        output_fields = {
            "canonical_s3_key": f"s3://{CANONICAL_BUCKET}/{s3_key}",
            "doc_title": canonical.title,
            "doc_date": doc_date,
            "doc_type": str(canonical.type),
            "sections_count": 1,
            "status": "success",
        }
        release_lock(evt.doc_id, "parse_canonical", output_fields)
        return PipelineEvent.from_dict({**event, **output_fields}).to_dict()

    except (AlreadySucceeded, StillRunning):
        raise
    except Exception as exc:
        logger.error("esma.parse_canonical_error", error=str(exc), doc_id=evt.doc_id)
        fail_lock(evt.doc_id, "parse_canonical", str(exc))
        raise
