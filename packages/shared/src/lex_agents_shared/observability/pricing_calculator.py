"""Anthropic token cost estimator backed by config/anthropic_prices.yaml (ADR 0031).

YAML format v2: price_schedules list with effective_from dates.
The active schedule is the most recent one with effective_from <= today.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# Resolve prices file relative to repo root (6 levels up from this file)
_DEFAULT_PRICES_PATH = Path(__file__).parents[5] / "config" / "anthropic_prices.yaml"

# Conservative hardcoded fallback — used only if the YAML cannot be loaded at all
_HARDCODED_DEFAULTS: dict[str, float] = {
    "input_per_mtok_usd": 15.00,
    "output_per_mtok_usd": 75.00,
    "cached_read_per_mtok_usd": 1.50,
    "cache_write_per_mtok_usd": 18.75,
}


@lru_cache(maxsize=1)
def _load_prices(prices_path: str) -> dict[str, Any]:
    try:
        with open(prices_path) as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]
    except Exception as exc:
        logger.warning("pricing_yaml_load_failed", path=prices_path, error=str(exc))
        return {}


def _active_schedule(data: dict[str, Any], as_of: date | None = None) -> dict[str, Any]:
    """Return the price schedule active on *as_of* (default: today).

    Selects the most recent entry with effective_from <= as_of from price_schedules.
    Falls back to an empty dict if no schedules are found.
    """
    schedules: list[dict[str, Any]] = data.get("price_schedules", [])
    if not schedules:
        return {}
    target = as_of or date.today()
    active: dict[str, Any] = {}
    for sched in schedules:
        ef = sched.get("effective_from", "")
        try:
            ef_date = date.fromisoformat(str(ef))
        except (ValueError, TypeError):
            continue
        if ef_date <= target:
            active = sched
    return active


class PricingCalculator:
    """Estimate USD cost of an Anthropic API call from token counts.

    Reads config/anthropic_prices.yaml (v2 versioned format, ADR 0031).
    Falls back to conservative defaults if the file is missing or the model
    is unknown — never raises an exception.

    Public API is unchanged from v1: estimate(model, input_tokens, output_tokens, ...).
    """

    def __init__(self, prices_path: str | None = None) -> None:
        self._path = prices_path or os.getenv(
            "ANTHROPIC_PRICES_PATH", str(_DEFAULT_PRICES_PATH)
        )

    def _prices_for(self, model: str, as_of: date | None = None) -> dict[str, float]:
        data = _load_prices(self._path)
        schedule = _active_schedule(data, as_of)
        models: dict[str, Any] = schedule.get("models", {})

        if model in models:
            return dict(models[model])

        logger.warning("pricing_unknown_model", model=model, path=self._path)
        default = models.get("_default")
        if default:
            return dict(default)
        return dict(_HARDCODED_DEFAULTS)

    def _discount(self, as_of: date | None = None) -> float:
        data = _load_prices(self._path)
        schedule = _active_schedule(data, as_of)
        return float(schedule.get("discounts", {}).get("batch_api", 0.5))

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
        batch: bool = False,
        as_of: date | None = None,
    ) -> float:
        """Return estimated USD cost. Always >= 0.

        Args:
            model: Anthropic model identifier.
            input_tokens: Total input tokens (including cached ones).
            output_tokens: Output tokens.
            cached_tokens: Tokens served from cache (subset of input_tokens).
            cache_write_tokens: New cache-write tokens (charged at write rate).
            batch: Apply Batch API 50% discount if True.
            as_of: Use price schedule effective on this date (default: today).
        """
        p = self._prices_for(model, as_of)
        billable_input = max(0, input_tokens - cached_tokens)
        cost = (
            billable_input * p.get("input_per_mtok_usd", 15.0) / 1_000_000
            + output_tokens * p.get("output_per_mtok_usd", 75.0) / 1_000_000
            + cached_tokens * p.get("cached_read_per_mtok_usd", 1.5) / 1_000_000
            + cache_write_tokens * p.get("cache_write_per_mtok_usd", 18.75) / 1_000_000
        )
        if batch:
            cost *= 1.0 - self._discount(as_of)
        return round(cost, 8)
