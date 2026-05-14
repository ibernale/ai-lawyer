"""format_sensor — hourly Lambda that detects source format changes.

Checks HEAD requests to each source's canonical URL, compares ETag/Last-Modified
against DynamoDB fingerprints table. On change: emits CloudWatch metric + logs
a structured warning for downstream alerting (GitHub issue creation via OIDC
is handled externally by the alerting pipeline in Fase 10).

Environment variables:
  FINGERPRINTS_TABLE : DynamoDB table name for fingerprint storage
  GITHUB_REPO        : GitHub repository slug (default: ibernale/ai-lawyer)
  LOG_LEVEL          : Logging level (default: INFO)
"""

from __future__ import annotations

import hashlib
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

FINGERPRINTS_TABLE = os.environ.get("FINGERPRINTS_TABLE", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "ibernale/ai-lawyer")

# Map source name → canonical URL to check
SOURCE_URLS: dict[str, str] = {
    "boe": "https://www.boe.es/boe/dias/2024/01/01/",
    "eur_lex": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2554",
    "aepd": "https://www.aepd.es/es/informes-y-resoluciones/resoluciones",
    "edpb": "https://edpb.europa.eu/our-work-tools/our-documents_en",
    "bde": "https://www.bde.es/wbe/es/normativa/circulares-otra-normativa/",
    "eba": "https://www.eba.europa.eu/regulation-and-policy",
    "esma": "https://www.esma.europa.eu/document-library",
    "legislation_uk": "https://www.legislation.gov.uk/new",
    "fca": "https://www.fca.org.uk/news/policy-statements",
}

dynamodb = boto3.resource("dynamodb")
cloudwatch = boto3.client("cloudwatch")


def _get_fingerprint(url: str) -> str:
    """Make HEAD request and return fingerprint of ETag+Last-Modified+Content-Length.

    Returns an empty string if the HEAD request fails. Failures are logged at
    WARNING level without including the URL response body (PII safety).
    """
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "lex-agents-format-sensor/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            etag = resp.headers.get("ETag", "")
            last_mod = resp.headers.get("Last-Modified", "")
            content_len = resp.headers.get("Content-Length", "")
            raw = f"{etag}|{last_mod}|{content_len}"
            return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except Exception as exc:
        logger.warning("format_sensor.head_failed source_host=%s error=%s", url.split("/")[2], str(exc))
        return ""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Hourly Lambda handler: checks all source fingerprints and emits metrics on change."""
    if not FINGERPRINTS_TABLE:
        logger.error("format_sensor.missing_env FINGERPRINTS_TABLE not set")
        raise ValueError("FINGERPRINTS_TABLE environment variable is required")

    table = dynamodb.Table(FINGERPRINTS_TABLE)
    changes: list[str] = []
    checked_at = datetime.now(timezone.utc).isoformat()

    for source, url in SOURCE_URLS.items():
        fingerprint = _get_fingerprint(url)
        if not fingerprint:
            logger.warning("format_sensor.skip_empty_fingerprint source=%s", source)
            continue

        response = table.get_item(Key={"source": source})
        stored = response.get("Item", {}).get("fingerprint", "")

        if stored and stored != fingerprint:
            logger.warning(
                "format_sensor.change_detected source=%s previous=%s current=%s",
                source,
                stored,
                fingerprint,
            )
            changes.append(source)

            # Emit CloudWatch metric for alerting
            try:
                cloudwatch.put_metric_data(
                    Namespace="LexAgents/Pipeline",
                    MetricData=[{
                        "MetricName": "FormatChangeDetected",
                        "Dimensions": [{"Name": "Source", "Value": source}],
                        "Value": 1.0,
                        "Unit": "Count",
                    }],
                )
            except Exception as exc:
                logger.error("format_sensor.cloudwatch_failed source=%s error=%s", source, str(exc))

        # Update stored fingerprint (upsert)
        table.put_item(Item={
            "source": source,
            "fingerprint": fingerprint,
            "checked_at": checked_at,
        })

    logger.info(
        "format_sensor.done sources_checked=%d changes=%d",
        len(SOURCE_URLS),
        len(changes),
    )
    return {
        "changes_detected": changes,
        "sources_checked": list(SOURCE_URLS.keys()),
        "checked_at": checked_at,
    }
