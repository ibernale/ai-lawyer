"""parse_canonical handler for AEPD — Lambda step in ingest_aepd state machine.

Reads a raw AEPD HTML document from S3, parses it into canonical JSON format
using AepdSource.parse_to_canonical(), and stores the result in the canonical
S3 bucket.

Input  (PipelineEvent fields used):
  source          : "aepd"
  run_date        : "YYYY-MM-DD"
  doc_id          : set by fetch_raw (e.g. "aepd/2026-05-14/PS_00001_2024")
  raw_s3_key      : "s3://<raw-bucket>/..." set by fetch_raw

Output (new fields added to PipelineEvent):
  canonical_s3_key : "s3://<canonical-bucket>/aepd/<year>/<doc_id_safe>.json"
  doc_title        : resolution title
  doc_date         : ISO date
  doc_type         : "resolution"
  sections_count   : 1
  status           : "success" | "error"

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
    """Read bytes from an s3://bucket/key URI."""
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the AEPD ParseCanonical stage."""
    from lex_agents_ingest.canonical import RawDocument
    from lex_agents_ingest.sources.aepd import AepdSource

    evt = PipelineEvent.from_dict(event)
    logger.info("aepd.parse_canonical_start", doc_id=evt.doc_id)

    try:
        try:
            acquire_lock(evt.doc_id, "parse_canonical")
        except AlreadySucceeded as exc:
            logger.info("aepd.parse_canonical_cached", doc_id=evt.doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise

        # Read raw HTML from S3
        raw_bytes = _read_s3_object(evt.raw_s3_key)

        # Reconstruct source_id from doc_id: "aepd/2026-05-14/PS_00001_2024" → "PS/00001/2024"
        # The last segment is the safe_id; convert underscores back to slashes for PS pattern
        doc_id_last = evt.doc_id.split("/")[-1]
        if doc_id_last == "batch":
            # Batch placeholder — nothing to parse individually
            raise ValueError("Batch doc_id 'batch' cannot be parsed directly; use per-document events")
        source_id = doc_id_last.replace("_", "/", 2)  # PS_00001_2024 → PS/00001/2024

        raw_doc = RawDocument(
            source="aepd",
            source_id=source_id,
            raw_url=evt.raw_s3_key,
            content_type="html",
            raw_bytes=raw_bytes,
            fetched_at=datetime.utcnow(),
        )

        # parse_to_canonical is a pure function — no network calls
        source = AepdSource.__new__(AepdSource)
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

        # Write canonical JSON to S3
        safe_doc_id = evt.doc_id.replace("/", "_")
        s3_key = f"aepd/{evt.run_date}/{safe_doc_id}.json"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=CANONICAL_BUCKET,
            Key=s3_key,
            Body=json.dumps(canonical_dict, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
            Metadata={"doc_id": evt.doc_id, "source": "aepd"},
        )

        logger.info("aepd.parse_canonical_done", doc_id=evt.doc_id, s3_key=s3_key)

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
        logger.error("aepd.parse_canonical_error", error=str(exc), doc_id=evt.doc_id)
        fail_lock(evt.doc_id, "parse_canonical", str(exc))
        raise
