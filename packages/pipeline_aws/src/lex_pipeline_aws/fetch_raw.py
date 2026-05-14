"""Lambda handler — FetchRaw stage (ADR 0047).

Fetches a legal document from its source API (BOE / EUR-Lex) and stores
the raw bytes in the S3 raw bucket.

Input  (PipelineEvent fields used):
  source    : "boe" | "eur_lex"
  run_date  : "YYYY-MM-DD"

Output (new fields added to PipelineEvent):
  doc_id          : "<source>/<run_date>/<document_id>"
  raw_s3_key      : "s3://<raw-bucket>/<source>/<year>/<document_id>.xml"
  raw_content_type: "application/xml"
  raw_byte_size   : <int>
  status          : "success" | "error"

Environment variables:
  RAW_BUCKET_NAME       : S3 bucket name for raw documents
  BOE_BASE_URL          : BOE API base URL (default: https://www.boe.es/datosabiertos/api)
  EUR_LEX_BASE_URL      : EUR-Lex base URL (default: https://eur-lex.europa.eu)
  IDEMPOTENCY_TABLE     : DynamoDB table name for idempotency
  LEX_ENV               : "dev" | "staging" | "prod"
"""

from __future__ import annotations

import os
import urllib.request
from datetime import date, datetime
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
BOE_BASE_URL = os.environ.get("BOE_BASE_URL", "https://www.boe.es/datosabiertos/api")
EUR_LEX_BASE_URL = os.environ.get("EUR_LEX_BASE_URL", "https://eur-lex.europa.eu")


# ---------------------------------------------------------------------------
# Source-specific fetchers
# ---------------------------------------------------------------------------

def _fetch_boe_summary(run_date: str) -> tuple[str, bytes, str]:
    """Fetch BOE daily summary XML for run_date.

    Returns:
        (doc_id, raw_bytes, content_type)
    """
    # BOE API: GET /sumario/{YYYYMMDD}
    date_compact = run_date.replace("-", "")
    url = f"{BOE_BASE_URL}/sumario/{date_compact}"
    logger.info("fetch_boe_summary", url=url, run_date=run_date)

    req = urllib.request.Request(url, headers={"Accept": "application/xml"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw_bytes = resp.read()
        content_type = resp.headers.get("Content-Type", "application/xml").split(";")[0].strip()

    doc_id = f"boe/sumario/{run_date}"
    return doc_id, raw_bytes, content_type


def _fetch_eur_lex_recent(run_date: str) -> tuple[str, bytes, str]:
    """Fetch EUR-Lex recent banking regulations for run_date.

    Uses EUR-Lex SPARQL endpoint to get document list, then fetches XML.
    For Fase 9.2 this is a stub that returns placeholder bytes.
    Full implementation in Fase 9.3 (source-ingester subagent).

    Returns:
        (doc_id, raw_bytes, content_type)
    """
    logger.info("fetch_eur_lex_recent", run_date=run_date)

    # TODO Fase 9.3: implement real EUR-Lex SPARQL + XML fetch
    # For now, return a minimal placeholder so the pipeline can be tested end-to-end.
    placeholder = f'<?xml version="1.0"?><root source="eur_lex" date="{run_date}"><stub/></root>'.encode()
    doc_id = f"eur_lex/recent/{run_date}"
    return doc_id, placeholder, "application/xml"


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the FetchRaw stage."""
    evt = PipelineEvent.from_dict(event)
    logger.info("fetch_raw_start", source=evt.source, run_date=evt.run_date)

    try:
        # Fetch document
        if evt.source == "boe":
            doc_id, raw_bytes, content_type = _fetch_boe_summary(evt.run_date)
        elif evt.source == "eur_lex":
            doc_id, raw_bytes, content_type = _fetch_eur_lex_recent(evt.run_date)
        else:
            raise ValueError(f"Unknown source: {evt.source!r}")

        evt.doc_id = doc_id

        # Idempotency: check DynamoDB before writing to S3
        try:
            acquire_lock(doc_id, "fetch_raw")
        except AlreadySucceeded as exc:
            logger.info("fetch_raw_cached", doc_id=doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise  # Step Functions will retry

        # Upload to S3
        year = evt.run_date[:4]
        s3_key = f"{evt.source}/{year}/{doc_id.replace('/', '_')}.xml"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=RAW_BUCKET,
            Key=s3_key,
            Body=raw_bytes,
            ContentType=content_type,
            Metadata={
                "source": evt.source,
                "run_date": evt.run_date,
                "doc_id": doc_id,
            },
        )

        logger.info(
            "fetch_raw_uploaded",
            doc_id=doc_id,
            s3_key=s3_key,
            bytes=len(raw_bytes),
        )

        output_fields = {
            "doc_id": doc_id,
            "raw_s3_key": f"s3://{RAW_BUCKET}/{s3_key}",
            "raw_content_type": content_type,
            "raw_byte_size": len(raw_bytes),
            "status": "success",
        }
        release_lock(doc_id, "fetch_raw", output_fields)
        return PipelineEvent.from_dict({**event, **output_fields}).to_dict()

    except (AlreadySucceeded, StillRunning):
        raise
    except Exception as exc:
        logger.error("fetch_raw_error", error=str(exc), source=evt.source, run_date=evt.run_date)
        if evt.doc_id:
            fail_lock(evt.doc_id, "fetch_raw", str(exc))
        evt.status = "error"
        evt.error_message = str(exc)
        raise  # Let Step Functions handle retry/catch
