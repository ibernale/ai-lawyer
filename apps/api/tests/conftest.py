"""Shared pytest fixtures and hooks for the lex-agents-api test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Clear the module-level rate limiter storage before each test.

    The @limiter.limit() decorator captures the module-level Limiter at import
    time. Its in-memory storage would otherwise accumulate across test functions
    within the same process, causing tests that call /auth/token many times to
    affect subsequent tests that expect clean rate-limit buckets.
    """
    from lex_agents_api.limiter import limiter

    limiter._storage.reset()
