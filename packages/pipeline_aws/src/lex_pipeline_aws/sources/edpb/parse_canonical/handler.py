"""parse_canonical handler for EDPB — Lambda step in ingest_edpb state machine.

Reads a raw EDPB PDF or HTML document from S3, parses it into canonical JSON
using EdpbSource.parse_to_canonical(), and stores in the canonical S3 bucket.

Note: EdpbSource.parse_to_canonical() is a pure function (no network calls).
The content_type stored in S3 metadata determines pdf vs html branch.

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


def _read_s3_object(s3_uri: str) -> tuple[bytes, str]:
    """Read bytes and content-type from an s3://bucket/key URI."""
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    content_type = resp.get("ContentType", "application/pdf")
    return resp["Body"].read(), content_type


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the EDPB ParseCanonical stage."""
    from lex_agents_ingest.canonical import RawDocument
    from lex_agents_ingest.sources.edpb import EdpbSource

    evt = PipelineEvent.from_dict(event)
    logger.info("edpb.parse_canonical_start", doc_id=evt.doc_id)

    try:
        try:
            acquire_lock(evt.doc_id, "parse_canonical")
        except AlreadySucceeded as exc:
            logger.info("edpb.parse_canonical_cached", doc_id=evt.doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise

        raw_bytes, content_type_header = _read_s3_object(evt.raw_s3_key)

        # Determine content_type for RawDocument: must be "pdf" | "html" | "xml"
        if "pdf" in content_type_header.lower() or evt.raw_s3_key.endswith(".pdf"):
            raw_content_type = "pdf"
        else:
            raw_content_type = "html"

        # Recover the original doc slug from doc_id: "edpb/2026-05-14/<safe_id>" → "<safe_id>"
        doc_id_last = evt.doc_id.split("/")[-1]

        raw_doc = RawDocument(
            source="edpb",
            source_id=doc_id_last,
            raw_url=evt.raw_s3_key,
            content_type=raw_content_type,  # type: ignore[arg-type]
            raw_bytes=raw_bytes,
            fetched_at=datetime.utcnow(),
        )

        # parse_to_canonical is pure — instantiate without network client
        source = EdpbSource.__new__(EdpbSource)
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
        }

        safe_doc_id = evt.doc_id.replace("/", "_")
        s3_key = f"edpb/{evt.run_date}/{safe_doc_id}.json"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=CANONICAL_BUCKET,
            Key=s3_key,
            Body=json.dumps(canonical_dict, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
            Metadata={"doc_id": evt.doc_id, "source": "edpb"},
        )

        logger.info("edpb.parse_canonical_done", doc_id=evt.doc_id, s3_key=s3_key)

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
        logger.error("edpb.parse_canonical_error", error=str(exc), doc_id=evt.doc_id)
        fail_lock(evt.doc_id, "parse_canonical", str(exc))
        raise
