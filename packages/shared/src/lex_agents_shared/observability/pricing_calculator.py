"""Anthropic token cost estimator backed by config/anthropic_prices.yaml (ADR 0031)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Resolve prices file relative to repo root: go up from this file to find config/
_DEFAULT_PRICES_PATH = Path(__file__).parents[5] / "config" / "anthropic_prices.yaml"


@lru_cache(maxsize=1)
def _load_prices(prices_path: str) -> dict[str, Any]:
    try:
        with open(prices_path) as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]
    except Exception as exc:
        logger.warning("pricing_yaml_load_failed", path=prices_path, error=str(exc))
        return {}


class PricingCalculator:
    """Estimate USD cost of an Anthropic API call from token counts.

    Reads config/anthropic_prices.yaml. Falls back to conservative defaults
    if the file is missing or the model is unknown.
    """

    def __init__(self, prices_path: str | None = None) -> None:
        self._path = prices_path or os.getenv(
            "ANTHROPIC_PRICES_PATH", str(_DEFAULT_PRICES_PATH)
        )

    def _prices_for(self, model: str) -> dict[str, float]:
        data = _load_prices(self._path)
        models: dict[str, Any] = data.get("models", {})
        if model in models:
            return models[model]
        logger.warning("pricing_unknown_model", model=model)
        return models.get("_default", {
            "input_per_mtok": 15.00,
            "output_per_mtok": 75.00,
            "cached_per_mtok": 1.50,
            "cache_write_per_mtok": 18.75,
        })

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
        batch: bool = False,
    ) -> float:
        """Return estimated USD cost. Always >= 0."""
        p = self._prices_for(model)
        billable_input = max(0, input_tokens - cached_tokens)
        cost = (
            billable_input * p.get("input_per_mtok", 15.0) / 1_000_000
            + output_tokens * p.get("output_per_mtok", 75.0) / 1_000_000
            + cached_tokens * p.get("cached_per_mtok", 1.5) / 1_000_000
            + cache_write_tokens * p.get("cache_write_per_mtok", 18.75) / 1_000_000
        )
        if batch:
            data = _load_prices(self._path)
            discount = data.get("discounts", {}).get("batch_api", 0.5)
            cost *= 1.0 - discount
        return round(cost, 8)
