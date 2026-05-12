"""Anthropic Admin API client — Usage & Cost reports (ADR 0031).

Requires ANTHROPIC_ADMIN_KEY (separate from the inference API key).
Without it the client enters estimation_only mode and all methods return
empty reports — never raises, never blocks the main request path.

Rate limits: ~100 req/min (much more permissive than inference API).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import structlog
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_BASE_URL = "https://api.anthropic.com"
_API_VERSION = "2023-06-01"
_DEFAULT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UsageBucket(BaseModel):
    timestamp: datetime
    model: str | None = None
    service_tier: str | None = None
    context_window: str | None = None
    workspace: str | None = None
    uncached_input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0


class UsageReport(BaseModel):
    buckets: list[UsageBucket]
    fetched_at: datetime
    bucket_width: str


class CostBucket(BaseModel):
    timestamp: datetime
    description: str | None = None
    cost_usd: float = 0.0
    cost_type: str | None = None
    workspace: str | None = None


class CostReport(BaseModel):
    buckets: list[CostBucket]
    fetched_at: datetime
    bucket_width: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class AnthropicAdminClient:
    """Async client for the Anthropic Admin API (usage + cost endpoints).

    If admin_api_key is None or empty, all methods return empty reports
    without making any network calls (estimation_only=True).
    """

    def __init__(
        self,
        admin_api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        key = admin_api_key or os.getenv("ANTHROPIC_ADMIN_KEY", "")
        self.estimation_only = not bool(key)
        self._key = key
        self._timeout = timeout

        if self.estimation_only:
            logger.info("anthropic_admin_client_estimation_only")
        else:
            logger.info("anthropic_admin_client_ready")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_usage_report(
        self,
        starting_at: datetime,
        ending_at: datetime,
        bucket_width: Literal["1m", "1h", "1d"] = "1d",
        group_by: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> UsageReport:
        """Fetch hourly/daily token usage grouped by model, service_tier, etc."""
        if self.estimation_only:
            return UsageReport(
                buckets=[], fetched_at=datetime.now(UTC), bucket_width=bucket_width
            )
        params = self._build_params(starting_at, ending_at, bucket_width, group_by, filters)
        raw = await self._get("/v1/usage", params)
        buckets = [
            UsageBucket(
                timestamp=b.get("start_time", b.get("timestamp", "")),
                model=b.get("model"),
                service_tier=b.get("service_tier"),
                context_window=b.get("context_window_size"),
                workspace=b.get("workspace", ""),
                uncached_input_tokens=b.get("input_tokens", 0),
                cached_input_tokens=b.get("cache_read_input_tokens", 0),
                cache_creation_tokens=b.get("cache_creation_input_tokens", 0),
                output_tokens=b.get("output_tokens", 0),
            )
            for b in raw.get("data", [])
        ]
        return UsageReport(buckets=buckets, fetched_at=datetime.now(UTC), bucket_width=bucket_width)

    async def get_cost_report(
        self,
        starting_at: datetime,
        ending_at: datetime,
        bucket_width: Literal["1m", "1h", "1d"] = "1d",
        group_by: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> CostReport:
        """Fetch cost report grouped by workspace or description."""
        if self.estimation_only:
            return CostReport(
                buckets=[], fetched_at=datetime.now(UTC), bucket_width=bucket_width
            )
        params = self._build_params(starting_at, ending_at, bucket_width, group_by, filters)
        raw = await self._get("/v1/costs", params)
        buckets = [
            CostBucket(
                timestamp=b.get("start_time", b.get("timestamp", "")),
                description=b.get("description"),
                cost_usd=float(b.get("total_cost", b.get("cost", 0.0))),
                cost_type=b.get("cost_type", "tokens"),
                workspace=b.get("workspace", ""),
            )
            for b in raw.get("data", [])
        ]
        return CostReport(buckets=buckets, fetched_at=datetime.now(UTC), bucket_width=bucket_width)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_params(
        self,
        starting_at: datetime,
        ending_at: datetime,
        bucket_width: str,
        group_by: list[str] | None,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "start_date": starting_at.date().isoformat(),
            "end_date": ending_at.date().isoformat(),
            "bucket_width": bucket_width,
        }
        if group_by:
            params["group_by[]"] = group_by
        if filters:
            params.update(filters)
        return params

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self._key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(base_url=_BASE_URL, timeout=self._timeout) as client:
            resp = await client.get(path, params=params, headers=headers)

        if resp.status_code in (401, 403):
            logger.warning(
                "anthropic_admin_api_auth_failed",
                status=resp.status_code,
                path=path,
            )
            return {"data": []}  # non-fatal — estimation_only fallback

        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
