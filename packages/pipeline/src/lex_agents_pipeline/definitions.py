"""Dagster Definitions root — assembles all assets, resources, jobs, schedules, sensors."""

from __future__ import annotations

import os

from dagster import Definitions

from lex_agents_pipeline.assets.canonical import ALL_CANONICAL_ASSETS
from lex_agents_pipeline.assets.chunked import ALL_CHUNKED_ASSETS
from lex_agents_pipeline.assets.contextualized import ALL_CONTEXTUALIZED_ASSETS
from lex_agents_pipeline.assets.embedded import ALL_EMBEDDED_ASSETS
from lex_agents_pipeline.assets.indexed import ALL_INDEXED_ASSETS, ALL_INDEXED_CHECKS
from lex_agents_pipeline.assets.raw import ALL_RAW_ASSETS, ALL_RAW_CHECKS
from lex_agents_pipeline.jobs.ingest_jobs import ALL_JOBS
from lex_agents_pipeline.resources.clients import (
    AnthropicResource,
    EmbedderResource,
    QdrantResource,
)

# ---------------------------------------------------------------------------
# Lazy imports for schedules and sensors (may not exist yet)
# ---------------------------------------------------------------------------

_schedules = []
_sensors = []

try:
    from lex_agents_pipeline.schedules.cron import ALL_SCHEDULES
    _schedules = ALL_SCHEDULES
except ImportError:
    pass

try:
    from lex_agents_pipeline.sensors.format_change import (
        embedding_model_change_sensor,
        source_format_change_sensor,
    )
    _sensors = [source_format_change_sensor, embedding_model_change_sensor]
except ImportError:
    pass

try:
    from lex_agents_pipeline.assets.admin.cost_sync import (
        anthropic_cost_sync,
        cost_reconciliation_daily,
        cost_positive_if_local_active,
        usage_report_not_empty,
    )
    _finops_assets = [anthropic_cost_sync, cost_reconciliation_daily]
    _finops_checks = [usage_report_not_empty, cost_positive_if_local_active]
except ImportError:
    _finops_assets = []
    _finops_checks = []

# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

_resources = {
    "anthropic": AnthropicResource(
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    ),
    "qdrant": QdrantResource(
        url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        api_key=os.environ.get("QDRANT_API_KEY", ""),
        collection_name=os.environ.get("QDRANT_COLLECTION", "lex_legal_docs"),
    ),
    "embedder": EmbedderResource(
        model_name=os.environ.get("EMBEDDER_MODEL", "BAAI/bge-m3"),
    ),
}

# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

defs = Definitions(
    assets=(
        ALL_RAW_ASSETS
        + ALL_CANONICAL_ASSETS
        + ALL_CHUNKED_ASSETS
        + ALL_CONTEXTUALIZED_ASSETS
        + ALL_EMBEDDED_ASSETS
        + ALL_INDEXED_ASSETS
        + _finops_assets
    ),
    asset_checks=ALL_RAW_CHECKS + ALL_INDEXED_CHECKS + _finops_checks,
    resources=_resources,
    jobs=ALL_JOBS,
    schedules=_schedules,
    sensors=_sensors,
)
