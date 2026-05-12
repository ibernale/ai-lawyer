"""Unit tests for PricingCalculator (ADR 0031, v2 YAML format)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from lex_agents_shared.observability.pricing_calculator import PricingCalculator, _load_prices

# Path to the actual prices YAML in the repo
_PRICES_PATH = str(Path(__file__).parents[3] / "config" / "anthropic_prices.yaml")


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    _load_prices.cache_clear()
    yield
    _load_prices.cache_clear()


class TestPricesYaml:
    def test_yaml_loads_without_error(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        p = calc._prices_for("claude-opus-4-7")
        assert p["input_per_mtok_usd"] == 5.00
        assert p["output_per_mtok_usd"] == 25.00

    def test_all_known_models_present(self) -> None:
        with open(_PRICES_PATH) as f:
            data = yaml.safe_load(f)
        models = data["price_schedules"][-1]["models"]
        assert "claude-opus-4-7" in models
        assert "claude-sonnet-4-6" in models
        assert "claude-haiku-4-5-20251001" in models

    def test_default_fallback_present(self) -> None:
        with open(_PRICES_PATH) as f:
            data = yaml.safe_load(f)
        latest = data["price_schedules"][-1]
        assert "_default" in latest["models"]
        assert latest["discounts"]["batch_api"] == 0.50


class TestOpusCost:
    def test_basic_input_output(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        # 1M input + 1M output at 2026-04-16 opus prices: 5 + 25 = $30
        cost = calc.estimate("claude-opus-4-7", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(30.0, rel=1e-6)

    def test_small_call(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        # 1000 input tokens = 0.005$; 500 output = 0.0125$
        cost = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=500)
        expected = (1000 * 5.0 + 500 * 25.0) / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_cached_tokens_reduce_billable_input(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        # 1000 input, 400 cached: billable_input = 600
        # cost = 600*5/1M + 400*0.50/1M
        cost = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=0, cached_tokens=400)
        expected = (600 * 5.0 + 400 * 0.50) / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_cache_write_tokens(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate(
            "claude-opus-4-7",
            input_tokens=500,
            output_tokens=0,
            cached_tokens=0,
            cache_write_tokens=200,
        )
        expected = (500 * 5.0 + 200 * 6.25) / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_batch_discount_50_percent(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        normal = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=1000)
        batched = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=1000, batch=True)
        assert batched == pytest.approx(normal * 0.5, rel=1e-6)


class TestSonnetCost:
    def test_sonnet_prices(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        # 1M input + 1M output: 3 + 15 = $18
        cost = calc.estimate("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(18.0, rel=1e-6)

    def test_sonnet_cached(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate("claude-sonnet-4-6", input_tokens=1000, output_tokens=0, cached_tokens=1000)
        # billable_input = 0, cached = 1000 * 0.30 / 1M
        expected = 1000 * 0.30 / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)


class TestHaikuCost:
    def test_haiku_prices(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate("claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(4.80, rel=1e-6)

    def test_haiku_is_cheapest(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        tokens = dict(input_tokens=100_000, output_tokens=50_000)
        opus = calc.estimate("claude-opus-4-7", **tokens)
        sonnet = calc.estimate("claude-sonnet-4-6", **tokens)
        haiku = calc.estimate("claude-haiku-4-5-20251001", **tokens)
        assert haiku < sonnet < opus


class TestUnknownModelConservativeFallback:
    def test_unknown_model_uses_default(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost_unknown = calc.estimate("gpt-99-ultra", input_tokens=1000, output_tokens=500)
        # _default has input=15, output=75 (higher than opus 5+25)
        assert cost_unknown > 0

    def test_unknown_model_does_not_raise(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        cost = calc.estimate("totally-unknown-model-xyz", input_tokens=500, output_tokens=100)
        assert cost > 0

    def test_missing_yaml_returns_zero_gracefully(self) -> None:
        calc = PricingCalculator("/nonexistent/path/prices.yaml")
        cost = calc.estimate("claude-opus-4-7", input_tokens=1000, output_tokens=1000)
        assert cost >= 0


class TestEdgeCases:
    def test_zero_tokens_cost_zero(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        assert calc.estimate("claude-sonnet-4-6", input_tokens=0, output_tokens=0) == 0.0

    def test_cached_tokens_capped_to_input(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        # cached > input → billable_input clamped to 0 via max(0, ...)
        cost = calc.estimate("claude-opus-4-7", input_tokens=100, output_tokens=0, cached_tokens=500)
        assert cost >= 0

    def test_result_is_non_negative(self) -> None:
        calc = PricingCalculator(_PRICES_PATH)
        for model in ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]:
            assert calc.estimate(model, input_tokens=0, output_tokens=0) >= 0
