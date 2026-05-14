"""Lambda handler — ParseCanonical stage (ADR 0047).

Reads a raw XML document from S3, parses it into canonical JSON format,
and stores the result in the canonical S3 bucket.

Input  (PipelineEvent fields used):
  source          : "boe" | "eur_lex"
  run_date        : "YYYY-MM-DD"
  doc_id          : set by FetchRaw
  raw_s3_key      : "s3://<raw-bucket>/..." set by FetchRaw
  raw_content_type: set by FetchRaw

Output (new fields added to PipelineEvent):
  canonical_s3_key : "s3://<canonical-bucket>/<doc_id>.json"
  doc_title        : extracted from XML
  doc_date         : ISO date
  doc_type         : "reglamento" | "directiva" | "circular" | "sumario" | etc.
  sections_count   : number of top-level sections parsed

Environment variables:
  RAW_BUCKET_NAME       : S3 bucket for raw docs (to read from)
  CANONICAL_BUCKET_NAME : S3 bucket for canonical docs
  IDEMPOTENCY_TABLE     : DynamoDB table name
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
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


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_boe_sumario(xml_bytes: bytes) -> dict[str, Any]:
    """Parse BOE daily summary XML into canonical dict."""
    root = ET.fromstring(xml_bytes)

    # Extract date from <sumario><meta><fecha>DD/MM/YYYY</fecha></meta></sumario>
    fecha_el = root.find(".//fecha")
    doc_date = ""
    if fecha_el is not None and fecha_el.text:
        parts = fecha_el.text.strip().split("/")
        if len(parts) == 3:
            doc_date = f"{parts[2]}-{parts[1]}-{parts[0]}"

    # Count sections (diarios → secciones)
    sections = root.findall(".//seccion")

    # Collect items
    items = []
    for item in root.findall(".//item"):
        titulo = item.find("titulo")
        url_xml = item.find("urlXml")
        items.append({
            "title": titulo.text.strip() if titulo is not None and titulo.text else "",
            "url_xml": url_xml.text.strip() if url_xml is not None and url_xml.text else "",
            "id": item.get("id", ""),
        })

    return {
        "source": "boe",
        "doc_type": "sumario",
        "doc_date": doc_date,
        "doc_title": f"BOE Sumario {doc_date}",
        "sections_count": len(sections),
        "items": items,
        "items_count": len(items),
    }


def _parse_eur_lex_xml(xml_bytes: bytes) -> dict[str, Any]:
    """Parse EUR-Lex XML into canonical dict.

    Fase 9.2 stub — returns minimal structure.
    Full parser implemented in Fase 9.3.
    """
    root = ET.fromstring(xml_bytes)
    date_attr = root.get("date", "")

    return {
        "source": "eur_lex",
        "doc_type": "regulation",
        "doc_date": date_attr,
        "doc_title": "EUR-Lex document",
        "sections_count": 1,
        "items": [],
        "items_count": 0,
        "stub": True,
    }


def _read_s3_object(s3_uri: str) -> bytes:
    """Read bytes from an s3://bucket/key URI."""
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Step Functions Lambda handler for the ParseCanonical stage."""
    evt = PipelineEvent.from_dict(event)
    logger.info("parse_canonical_start", doc_id=evt.doc_id, source=evt.source)

    try:
        try:
            acquire_lock(evt.doc_id, "parse_canonical")
        except AlreadySucceeded as exc:
            logger.info("parse_canonical_cached", doc_id=evt.doc_id)
            return PipelineEvent.from_dict({**event, **exc.cached_output, "status": "success"}).to_dict()
        except StillRunning:
            raise

        # Read raw document from S3
        raw_bytes = _read_s3_object(evt.raw_s3_key)

        # Parse
        if evt.source == "boe":
            canonical = _parse_boe_sumario(raw_bytes)
        elif evt.source == "eur_lex":
            canonical = _parse_eur_lex_xml(raw_bytes)
        else:
            raise ValueError(f"Unknown source: {evt.source!r}")

        canonical["doc_id"] = evt.doc_id
        canonical["run_date"] = evt.run_date
        canonical["pipeline_version"] = evt.pipeline_version

        # Write canonical JSON to S3
        year = evt.run_date[:4]
        s3_key = f"{evt.source}/{year}/{evt.doc_id.replace('/', '_')}.json"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=CANONICAL_BUCKET,
            Key=s3_key,
            Body=json.dumps(canonical, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json",
            Metadata={"doc_id": evt.doc_id, "source": evt.source},
        )

        logger.info(
            "parse_canonical_done",
            doc_id=evt.doc_id,
            sections=canonical["sections_count"],
            s3_key=s3_key,
        )

        output_fields = {
            "canonical_s3_key": f"s3://{CANONICAL_BUCKET}/{s3_key}",
            "doc_title": canonical["doc_title"],
            "doc_date": canonical["doc_date"],
            "doc_type": canonical["doc_type"],
            "sections_count": canonical["sections_count"],
            "status": "success",
        }
        release_lock(evt.doc_id, "parse_canonical", output_fields)
        return PipelineEvent.from_dict({**event, **output_fields}).to_dict()

    except (AlreadySucceeded, StillRunning):
        raise
    except Exception as exc:
        logger.error("parse_canonical_error", error=str(exc), doc_id=evt.doc_id)
        fail_lock(evt.doc_id, "parse_canonical", str(exc))
        raise
