"""Shared rate-limiter instance — extracted to avoid circular imports."""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_key(request: Request) -> str:
    # Use IP only — trusting a client-supplied header would allow spoofing to evade limits.
    return get_remote_address(request) or "unknown"


limiter = Limiter(key_func=_rate_key)
