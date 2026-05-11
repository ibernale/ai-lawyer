"""
Sensors for detecting external changes that should trigger re-ingestion.

- source_format_change_sensor: hourly HEAD+structure-fingerprint check per source.
- embedding_model_change_sensor: detects EmbedderResource.model_name change and
  triggers re-materialisation of embedding/indexing assets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import urllib.request
from typing import TYPE_CHECKING

from dagster import (
    RunRequest,
    SensorEvaluationContext,
    SensorResult,
    SkipReason,
    sensor,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy job imports — won't blow up if ingest_jobs hasn't been created yet
# ---------------------------------------------------------------------------

def _get_ingest_all_job():  # type: ignore[return]
    try:
        from lex_agents_pipeline.jobs.ingest_jobs import ingest_all_job  # noqa: PLC0415
        return ingest_all_job
    except ImportError:
        return None


def _get_reindex_all_job():  # type: ignore[return]
    try:
        from lex_agents_pipeline.jobs.ingest_jobs import reindex_all_job  # noqa: PLC0415
        return reindex_all_job
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Source definitions: (name, url, fingerprint_strategy)
# fingerprint_strategy: "headers" | "content_hash"
# ---------------------------------------------------------------------------

SOURCES: list[dict[str, str]] = [
    {
        "name": "boe",
        "url": "https://boe.es/diario_boe/",
        "strategy": "headers",
    },
    {
        "name": "eur_lex",
        "url": "https://eur-lex.europa.eu/homepage.html",
        "strategy": "headers",
    },
    {
        "name": "aepd",
        "url": "https://www.aepd.es/es/documento/resoluciones",
        "strategy": "headers",
    },
    {
        "name": "edpb",
        "url": "https://www.edpb.europa.eu/our-work-tools/general-guidance/guidelines-recommendations-best-practices_en",
        "strategy": "headers",
    },
    {
        "name": "bde",
        "url": "https://www.bde.es/wbe/es/publicaciones/registros-oficiales-entidades/",
        "strategy": "headers",
    },
    {
        "name": "eba_qa",
        "url": "https://www.eba.europa.eu/single-rule-book-qa",
        "strategy": "headers",
    },
    {
        "name": "esma_qa",
        "url": "https://www.esma.europa.eu/convergence/q-and-a",
        "strategy": "headers",
    },
    {
        "name": "legislation_gov_uk",
        "url": "https://www.legislation.gov.uk/new",
        "strategy": "headers",
    },
    {
        "name": "fca_handbook",
        "url": "https://www.handbook.fca.org.uk/handbook",
        "strategy": "headers",
    },
]

_REQUEST_TIMEOUT = 15  # seconds


def _fingerprint_from_headers(headers: dict[str, str]) -> str:
    """Build a stable fingerprint from HTTP response headers."""
    relevant = {
        k.lower(): v
        for k, v in headers.items()
        if k.lower() in {"last-modified", "etag", "content-length", "x-amz-version-id"}
    }
    serialised = json.dumps(relevant, sort_keys=True)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


def _fingerprint_from_content(url: str) -> str:
    """Download up to 64 KB and hash the body for structure detection."""
    req = urllib.request.Request(url, headers={"User-Agent": "lex-agents-sensor/1.0"})
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:  # noqa: S310
        body = resp.read(65_536)
    return hashlib.sha256(body).hexdigest()[:16]


def _fetch_fingerprint(source: dict[str, str]) -> str | None:
    """Return fingerprint string, or None on failure."""
    try:
        req = urllib.request.Request(
            source["url"],
            method="HEAD",
            headers={"User-Agent": "lex-agents-sensor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:  # noqa: S310
            headers = dict(resp.headers)

        fp = _fingerprint_from_headers(headers)
        if fp == _fingerprint_from_headers({}):
            # Headers gave no useful signal; fall back to content hash
            fp = _fingerprint_from_content(source["url"])
        return fp
    except Exception as exc:  # noqa: BLE001
        logger.warning("sensor: fingerprint fetch failed for %s: %s", source["name"], exc)
        return None


def _try_create_github_issue(source_name: str, old_fp: str, new_fp: str) -> None:
    """Best-effort: open a GitHub issue if `gh` CLI is available."""
    title = f"[sensor] Source format change detected: {source_name}"
    body = (
        f"The ingestion sensor detected a structural change in source **{source_name}**.\n\n"
        f"- Previous fingerprint: `{old_fp}`\n"
        f"- New fingerprint:      `{new_fp}`\n\n"
        "Please review the source parser and update extraction logic if needed."
    )
    try:
        result = subprocess.run(  # noqa: S603
            ["gh", "issue", "create", "--title", title, "--body", body],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("sensor: GitHub issue created for %s: %s", source_name, result.stdout.strip())
        else:
            logger.warning(
                "sensor: gh issue create failed for %s: %s",
                source_name,
                result.stderr.strip(),
            )
    except FileNotFoundError:
        logger.info("sensor: gh CLI not available — skipping issue creation for %s", source_name)
    except subprocess.TimeoutExpired:
        logger.warning("sensor: gh CLI timed out for %s", source_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sensor: unexpected error calling gh for %s: %s", source_name, exc)


# ---------------------------------------------------------------------------
# Sensor 1 — source_format_change_sensor
# ---------------------------------------------------------------------------

@sensor(
    name="source_format_change_sensor",
    minimum_interval_seconds=3600,  # hourly
    description="Checks structure fingerprints for each source. Warns and creates a GitHub issue on change.",
)
def source_format_change_sensor(context: SensorEvaluationContext) -> SensorResult | SkipReason:
    """
    Runs hourly. For each source:
    1. Sends a HEAD request and builds an HTTP-header fingerprint.
    2. Compares against the value stored in cursor.
    3. On change: logs a WARNING and attempts to open a GitHub issue via `gh`.

    Returns SensorResult with metadata; does not trigger runs (format changes
    require human review before re-ingestion).
    """
    cursor_data: dict[str, str] = {}
    if context.cursor:
        try:
            cursor_data = json.loads(context.cursor)
        except json.JSONDecodeError:
            cursor_data = {}

    changed_sources: list[str] = []
    new_cursor: dict[str, str] = dict(cursor_data)

    for source in SOURCES:
        name = source["name"]
        new_fp = _fetch_fingerprint(source)
        if new_fp is None:
            # fetch failed — preserve existing cursor entry, don't false-alarm
            continue

        old_fp = cursor_data.get(name)
        new_cursor[name] = new_fp

        if old_fp is None:
            # First run — just record baseline
            logger.info("sensor: baseline fingerprint recorded for %s: %s", name, new_fp)
            continue

        if old_fp != new_fp:
            logger.warning(
                "sensor: FORMAT CHANGE detected for source '%s'  old=%s  new=%s",
                name,
                old_fp,
                new_fp,
            )
            changed_sources.append(name)
            _try_create_github_issue(name, old_fp, new_fp)

    return SensorResult(
        cursor=json.dumps(new_cursor),
        run_requests=[],  # format changes require human review; no auto-run
        dynamic_partitions_requests=[],
    )


# ---------------------------------------------------------------------------
# Sensor 2 — embedding_model_change_sensor
# ---------------------------------------------------------------------------

@sensor(
    name="embedding_model_change_sensor",
    minimum_interval_seconds=300,  # check every 5 minutes
    description=(
        "Detects EmbedderResource.model_name change vs last run and "
        "yields a RunRequest to re-materialise embedded/indexed assets."
    ),
)
def embedding_model_change_sensor(
    context: SensorEvaluationContext,
) -> SensorResult | SkipReason:
    """
    Reads the current embedding model name from the environment / resource config
    and compares it against the value stored in the cursor. If changed, it yields
    a RunRequest for the reindex_all_job (or ingest_all_job as fallback) so that
    all embedded and indexed assets are re-materialised with the new model.
    """
    import os  # noqa: PLC0415

    current_model = os.environ.get("EMBEDDER_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")

    cursor_data: dict[str, str] = {}
    if context.cursor:
        try:
            cursor_data = json.loads(context.cursor)
        except json.JSONDecodeError:
            cursor_data = {}

    last_model = cursor_data.get("embedder_model_name")
    new_cursor = {**cursor_data, "embedder_model_name": current_model}

    if last_model is None:
        # First evaluation — record baseline, don't trigger a run
        logger.info("embedding_model_change_sensor: baseline model recorded: %s", current_model)
        return SensorResult(cursor=json.dumps(new_cursor), run_requests=[])

    if last_model == current_model:
        return SkipReason(f"Embedding model unchanged: {current_model}")

    logger.warning(
        "embedding_model_change_sensor: model changed  old=%s  new=%s — scheduling re-index",
        last_model,
        current_model,
    )

    reindex_job = _get_reindex_all_job() or _get_ingest_all_job()
    if reindex_job is None:
        logger.warning(
            "embedding_model_change_sensor: no ingest/reindex job found — "
            "recording model change but not triggering a run"
        )
        return SensorResult(cursor=json.dumps(new_cursor), run_requests=[])

    run_request = RunRequest(
        run_key=f"embedding_model_change_{current_model}",
        run_config={
            "ops": {
                "embed_documents": {
                    "config": {"model_name": current_model, "force_reindex": True}
                }
            }
        },
        tags={
            "trigger": "embedding_model_change",
            "previous_model": last_model,
            "new_model": current_model,
        },
    )

    return SensorResult(cursor=json.dumps(new_cursor), run_requests=[run_request])
