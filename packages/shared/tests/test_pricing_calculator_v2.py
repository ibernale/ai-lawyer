"""Tests for PricingCalculator with versioned YAML format (v2, ADR 0031)."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pytest
import yaml

from lex_agents_shared.observability.pricing_calculator import (
    PricingCalculator,
    _active_schedule,
    _load_prices,
)

_PRICES_PATH = str(Path(__file__).parents[3] / "config" / "anthropic_prices.yaml")


@pytest.fixture(autouse=True)
def _clear_lru():
    _load_prices.cache_clear()
    yield
    _load_prices.cache_clear()


@pytest.fixture()
def tmp_prices(tmp_path: Path):
    """Write a temp prices YAML with two schedules for testing effective_from selection."""
    data = {
        "price_schedules": [
            {
                "effective_from": "2025-01-01",
                "models": {
                    "test-model": {
                        "input_per_mtok_usd": 10.0,
                        "output_per_mtok_usd": 50.0,
                        "cached_read_per_mtok_usd": 1.0,
                        "cache_write_per_mtok_usd": 12.5,
                    },
                    "_default": {
                        "input_per_mtok_usd": 15.0,
                        "output_per_mtok_usd": 75.0,
                        "cached_read_per_mtok_usd": 1.5,
                        "cache_write_per_mtok_usd": 18.75,
                    },
                },
                "discounts": {"batch_api": 0.50},
            },
            {
                "effective_from": "2026-04-16",
                "models": {
                    "test-model": {
                        "input_per_mtok_usd": 5.0,
                        "output_per_mtok_usd": 25.0,
                        "cached_read_per_mtok_usd": 0.5,
                        "cache_write_per_mtok_usd": 6.25,
                    },
                    "_default": {
                        "input_per_mtok_usd": 15.0,
                        "output_per_mtok_usd": 75.0,
                        "cached_read_per_mtok_usd": 1.5,
                        "cache_write_per_mtok_usd": 18.75,
                    },
                },
                "discounts": {"batch_api": 0.50},
            },
        ]
    }
    p = tmp_path / "prices.yaml"
    p.write_text(yaml.dump(data))
    return str(p)


class TestEffectiveDateSelection:
    def test_active_schedule_returns_latest_before_today(self, tmp_prices: str) -> None:
        _load_prices.cache_clear()
        data = _load_prices(tmp_prices)

        # Before first schedule: no match
        sched = _active_schedule(data, as_of=date(2024, 12, 31))
        assert sched == {}

        # After first, before second: first schedule
        sched = _active_schedule(data, as_of=date(2026, 1, 1))
        assert sched["models"]["test-model"]["input_per_mtok_usd"] == 10.0

        # On second effective_from: second schedule
        sched = _active_schedule(data, as_of=date(2026, 4, 16))
        assert sched["models"]["test-model"]["input_per_mtok_usd"] == 5.0

        # After second: still second schedule
        sched = _active_schedule(data, as_of=date(2026, 12, 31))
        assert sched["models"]["test-model"]["input_per_mtok_usd"] == 5.0

    def test_estimate_uses_correct_schedule(self, tmp_prices: str) -> None:
        _load_prices.cache_clear()
        calc = PricingCalculator(tmp_prices)

        old_cost = calc.estimate("test-model", input_tokens=1_000_000, output_tokens=0,
                                  as_of=date(2026, 1, 1))
        new_cost = calc.estimate("test-model", input_tokens=1_000_000, output_tokens=0,
                                  as_of=date(2026, 5, 12))
        assert old_cost == pytest.approx(10.0)
        assert new_cost == pytest.approx(5.0)


class TestRealYamlV2:
    def test_loads_v2_yaml(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate("claude-opus-4-7", input_tokens=1_000_000, output_tokens=0)
        assert cost > 0

    def test_opus_cost_v2(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        # 1M input + 1M output at 2026-04-16 prices: 5 + 25 = $30
        cost = calc.estimate(
            "claude-opus-4-7", input_tokens=1_000_000, output_tokens=1_000_000,
            as_of=date(2026, 5, 12),
        )
        assert cost == pytest.approx(30.0, rel=1e-6)

    def test_sonnet_cost_v2(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate(
            "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000,
            as_of=date(2026, 5, 12),
        )
        assert cost == pytest.approx(18.0, rel=1e-6)

    def test_haiku_cost_v2(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate(
            "claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000,
            as_of=date(2026, 5, 12),
        )
        assert cost == pytest.approx(4.80, rel=1e-6)

    def test_haiku_cheapest(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        tokens = dict(input_tokens=100_000, output_tokens=50_000)
        opus = calc.estimate("claude-opus-4-7", **tokens)
        sonnet = calc.estimate("claude-sonnet-4-6", **tokens)
        haiku = calc.estimate("claude-haiku-4-5-20251001", **tokens)
        assert haiku < sonnet < opus

    def test_cached_tokens_reduce_cost(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost_no_cache = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=0)
        cost_with_cache = calc.estimate(
            "claude-opus-4-7", input_tokens=1000, output_tokens=0, cached_tokens=1000
        )
        assert cost_with_cache < cost_no_cache

    def test_batch_discount(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        normal = calc.estimate("claude-sonnet-4-6", input_tokens=1000, output_tokens=1000)
        batched = calc.estimate("claude-sonnet-4-6", input_tokens=1000, output_tokens=1000, batch=True)
        assert batched == pytest.approx(normal * 0.5, rel=1e-6)


class TestUnknownModel:
    def test_unknown_model_uses_default(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate("gpt-99-unknown", input_tokens=1000, output_tokens=0)
        assert cost > 0

    def test_unknown_model_does_not_raise(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate("completely-unknown-xyz", input_tokens=500, output_tokens=100)
        assert cost >= 0

    def test_missing_yaml_does_not_raise(self) -> None:
        calc = PricingCalculator("/nonexistent/prices.yaml")
        cost = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=1000)
        assert cost >= 0

    def test_zero_tokens_cost_zero(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        assert calc.estimate("claude-sonnet-4-6", input_tokens=0, output_tokens=0) == 0.0
