"""Unit tests for QuotaTracker. ADR 0025."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lex_agents_ingest.quota import QuotaTracker
from lex_agents_shared.exceptions import CendojQuotaExhaustedError, CendojSuspendedError


@pytest.mark.unit
def test_initial_remaining_is_50(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    assert tracker.get_remaining() == 50


@pytest.mark.unit
def test_consume_decrements(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    tracker.consume()
    assert tracker.get_remaining() == 49


@pytest.mark.unit
def test_51st_request_raises_quota_exhausted(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    for _ in range(50):
        tracker.consume()
    assert tracker.get_remaining() == 0
    with pytest.raises(CendojQuotaExhaustedError):
        tracker.consume()


@pytest.mark.unit
def test_reset_daily_restores_quota(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    for _ in range(10):
        tracker.consume()
    assert tracker.get_remaining() == 40
    tracker.reset_daily()
    assert tracker.get_remaining() == 50


@pytest.mark.unit
def test_set_suspended_blocks_consume(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    tracker.set_suspended(reason="HTTP 429")
    assert tracker.is_suspended() is True
    with pytest.raises(CendojSuspendedError):
        tracker.consume()


@pytest.mark.unit
def test_reset_suspension_allows_consume(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=50)
    tracker.set_suspended(reason="HTTP 403")
    tracker.reset_suspension()
    assert tracker.is_suspended() is False
    result = tracker.consume()
    assert result is True
    assert tracker.get_remaining() == 49


@pytest.mark.unit
def test_get_remaining_respects_for_date(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=10)
    specific_date = date(2024, 1, 15)
    tracker.consume(for_date=specific_date)
    assert tracker.get_remaining(for_date=specific_date) == 9
    # Today's quota should still be intact
    assert tracker.get_remaining() == 10


@pytest.mark.unit
def test_reset_daily_for_specific_date(tmp_path: Path) -> None:
    tracker = QuotaTracker(db_path=tmp_path / "quota.db", daily_limit=10)
    specific_date = date(2024, 1, 15)
    for _ in range(5):
        tracker.consume(for_date=specific_date)
    assert tracker.get_remaining(for_date=specific_date) == 5
    tracker.reset_daily(for_date=specific_date)
    assert tracker.get_remaining(for_date=specific_date) == 10
