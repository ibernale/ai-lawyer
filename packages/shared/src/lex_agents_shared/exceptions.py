"""Shared exceptions for lex-agents source pipeline."""

from __future__ import annotations


class CommercialSourceDisabledError(Exception):
    """Raised when a commercial source is called without a verified license.

    This is a known, expected error — not an alert condition. It fires
    whenever any method of AranzadiSource, LaLeySource, or TirantSource is
    invoked without CONFIG_LICENSE_VERIFIED=true and the source enabled in
    config. See ADR 0029.
    """

    def __init__(self, source_name: str) -> None:
        super().__init__(
            f"Commercial source '{source_name}' is disabled. "
            f"A signed license and CONFIG_LICENSE_VERIFIED=true are required. "
            f"See docs/legal/comerciales-status.md and ADR 0029."
        )
        self.source_name = source_name


class CendojQuotaExhaustedError(Exception):
    """Raised when the CENDOJ daily request quota (50 req/day) is exhausted.

    Known, expected error. The orchestrator catches this and excludes CENDOJ
    from sources for the remainder of the day. See ADR 0025.
    """

    def __init__(self, remaining: int = 0) -> None:
        super().__init__(
            f"CENDOJ daily quota exhausted (remaining={remaining}). "
            f"Quota resets at 00:00 UTC. See ADR 0025."
        )
        self.remaining = remaining


class CendojSuspendedError(Exception):
    """Raised when CENDOJ access has been suspended after a 429/403/captcha.

    Requires manual intervention to reset. The Dagster asset checks
    QuotaTracker.is_suspended() at startup and fails with this error if true.
    Do NOT retry automatically — the suspension flag is evidence of good faith.
    See ADR 0025.
    """

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            f"CENDOJ access suspended (reason={reason!r}). "
            f"Manual reset required: delete SUSPENDED flag in data/cendoj_quota.db "
            f"after investigating. See docs/runbook.md and ADR 0025."
        )
        self.reason = reason
