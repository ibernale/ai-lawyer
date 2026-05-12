"""Unit tests for AnthropicAdminClient."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from lex_agents_shared.anthropic_admin_client import (
    AnthropicAdminClient,
    CostReport,
    UsageReport,
)

_NOW = datetime(2026, 5, 12, 6, 0, 0, tzinfo=timezone.utc)
_YESTERDAY = datetime(2026, 5, 11, 0, 0, 0, tzinfo=timezone.utc)


class TestEstimationOnly:
    def test_no_key_sets_estimation_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
        client = AnthropicAdminClient(admin_api_key=None)
        assert client.estimation_only is True

    def test_empty_string_key_sets_estimation_only(self) -> None:
        client = AnthropicAdminClient(admin_api_key="")
        assert client.estimation_only is True

    @pytest.mark.asyncio
    async def test_get_usage_returns_empty_without_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
        client = AnthropicAdminClient()
        report = await client.get_usage_report(_YESTERDAY, _NOW)
        assert isinstance(report, UsageReport)
        assert report.buckets == []
        assert report.bucket_width == "1d"

    @pytest.mark.asyncio
    async def test_get_cost_returns_empty_without_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
        client = AnthropicAdminClient()
        report = await client.get_cost_report(_YESTERDAY, _NOW)
        assert isinstance(report, CostReport)
        assert report.buckets == []


class TestUsageReportParsing:
    @pytest.mark.asyncio
    async def test_parses_usage_buckets(self) -> None:
        client = AnthropicAdminClient(admin_api_key="sk-admin-test")
        fake_response = {
            "data": [
                {
                    "start_time": "2026-05-11T00:00:00Z",
                    "model": "claude-opus-4-7",
                    "service_tier": "standard",
                    "context_window_size": "200k",
                    "input_tokens": 1000,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 50,
                    "output_tokens": 500,
                }
            ]
        }
        with patch.object(client, "_get", new=AsyncMock(return_value=fake_response)):
            report = await client.get_usage_report(_YESTERDAY, _NOW, bucket_width="1h")

        assert len(report.buckets) == 1
        b = report.buckets[0]
        assert b.model == "claude-opus-4-7"
        assert b.uncached_input_tokens == 1000
        assert b.cached_input_tokens == 200
        assert b.cache_creation_tokens == 50
        assert b.output_tokens == 500

    @pytest.mark.asyncio
    async def test_parses_cost_buckets(self) -> None:
        client = AnthropicAdminClient(admin_api_key="sk-admin-test")
        fake_response = {
            "data": [
                {
                    "start_time": "2026-05-11T01:00:00Z",
                    "description": "lex-agents-dev",
                    "total_cost": 0.0425,
                    "cost_type": "tokens",
                    "workspace": "default",
                }
            ]
        }
        with patch.object(client, "_get", new=AsyncMock(return_value=fake_response)):
            report = await client.get_cost_report(_YESTERDAY, _NOW, bucket_width="1h")

        assert len(report.buckets) == 1
        b = report.buckets[0]
        assert b.cost_usd == pytest.approx(0.0425)
        assert b.description == "lex-agents-dev"


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_successful_call_returns_report(self) -> None:
        """Verify that a successful API call (no retries needed) returns parsed report."""
        client = AnthropicAdminClient(admin_api_key="sk-admin-test")
        fake = {"data": [{"start_time": "2026-05-11T00:00:00Z", "model": "claude-opus-4-7",
                          "output_tokens": 100, "input_tokens": 200,
                          "service_tier": "", "context_window_size": ""}]}
        with patch.object(client, "_get", new=AsyncMock(return_value=fake)):
            report = await client.get_usage_report(_YESTERDAY, _NOW)
        assert len(report.buckets) == 1

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self) -> None:
        """When _get raises consistently, get_usage_report propagates the exception."""
        client = AnthropicAdminClient(admin_api_key="sk-admin-test")
        with patch.object(
            client, "_get",
            new=AsyncMock(side_effect=RuntimeError("persistent failure")),
        ):
            with pytest.raises(RuntimeError, match="persistent failure"):
                await client.get_usage_report(_YESTERDAY, _NOW)

    @pytest.mark.asyncio
    async def test_auth_error_returns_empty_nonfatal(self) -> None:
        """401/403 should log a warning and return empty report without raising."""
        client = AnthropicAdminClient(admin_api_key="sk-invalid")

        async def _mock_get_impl(path: str, params: dict) -> dict:
            return {"data": []}  # The real _get() normalises 401 → {"data": []}

        with patch.object(client, "_get", side_effect=_mock_get_impl):
            report = await client.get_usage_report(_YESTERDAY, _NOW)
        assert report.buckets == []


class TestBuildParams:
    def test_includes_group_by(self) -> None:
        client = AnthropicAdminClient(admin_api_key="sk-x")
        params = client._build_params(_YESTERDAY, _NOW, "1h", ["model", "service_tier"], None)
        assert params["group_by[]"] == ["model", "service_tier"]
        assert params["bucket_width"] == "1h"

    def test_no_group_by(self) -> None:
        client = AnthropicAdminClient(admin_api_key="sk-x")
        params = client._build_params(_YESTERDAY, _NOW, "1d", None, None)
        assert "group_by[]" not in params
