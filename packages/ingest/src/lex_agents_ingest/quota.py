"""CENDOJ request quota tracker — SQLite-backed, atomic, per ADR 0025."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import structlog

from lex_agents_shared.exceptions import CendojQuotaExhaustedError, CendojSuspendedError

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_AUDIT_LOG = Path("data/cendoj_audit.log")


class QuotaTracker:
    """SQLite-backed daily quota tracker for CENDOJ requests.

    Thread-safe via SQLite's BEGIN IMMEDIATE transactions. All timestamps
    are UTC. See ADR 0025.
    """

    def __init__(
        self,
        db_path: Path = Path("data/cendoj_quota.db"),
        daily_limit: int = 50,
    ) -> None:
        self._db_path = db_path
        self.daily_limit = daily_limit
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_log (
                    date TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS suspended (
                    active INTEGER NOT NULL DEFAULT 0,
                    reason TEXT,
                    suspended_at TEXT
                )
                """
            )
            # Ensure the suspended row exists (at most one row)
            conn.execute(
                "INSERT OR IGNORE INTO suspended (rowid, active) VALUES (1, 0)"
            )
            conn.commit()

    def _today_str(self, for_date: date | None = None) -> str:
        d = for_date or datetime.now(tz=timezone.utc).date()
        return d.isoformat()

    def _append_audit(self, for_date_str: str, remaining: int, status: str) -> None:
        ts = datetime.now(tz=timezone.utc).isoformat()
        line = f"{ts} consume date={for_date_str} remaining={remaining} status={status}\n"
        try:
            _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _AUDIT_LOG.open("a") as f:
                f.write(line)
        except OSError as exc:
            logger.warning("quota_tracker.audit_write_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_remaining(self, for_date: date | None = None) -> int:
        """Return how many requests are still available for *for_date* (default today UTC)."""
        date_str = self._today_str(for_date)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count FROM quota_log WHERE date = ?", (date_str,)
            ).fetchone()
        count = row[0] if row else 0
        return max(0, self.daily_limit - count)

    def consume(self, for_date: date | None = None) -> bool:
        """Atomically consume one quota unit.

        Returns True on success. Raises CendojQuotaExhaustedError if already at
        limit. Raises CendojSuspendedError if the tracker is suspended.
        """
        date_str = self._today_str(for_date)

        if self.is_suspended():
            self._append_audit(date_str, 0, "suspended")
            raise CendojSuspendedError("suspended flag set — manual reset required")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT count FROM quota_log WHERE date = ?", (date_str,)
            ).fetchone()
            current = row[0] if row else 0
            if current >= self.daily_limit:
                conn.execute("ROLLBACK")
                self._append_audit(date_str, 0, "exhausted")
                raise CendojQuotaExhaustedError(remaining=0)
            if row:
                conn.execute(
                    "UPDATE quota_log SET count = count + 1 WHERE date = ?",
                    (date_str,),
                )
            else:
                conn.execute(
                    "INSERT INTO quota_log (date, count) VALUES (?, 1)",
                    (date_str,),
                )
            conn.execute("COMMIT")

        remaining = self.daily_limit - (current + 1)
        self._append_audit(date_str, remaining, "ok")
        logger.info(
            "quota_tracker.consumed",
            date=date_str,
            remaining=remaining,
        )
        return True

    def is_suspended(self) -> bool:
        """Return True if access is currently suspended."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active FROM suspended WHERE rowid = 1"
            ).fetchone()
        return bool(row and row[0] == 1)

    def set_suspended(self, reason: str) -> None:
        """Suspend CENDOJ access. Requires manual reset via reset_suspension()."""
        ts = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE suspended SET active = 1, reason = ?, suspended_at = ? WHERE rowid = 1",
                (reason, ts),
            )
            conn.commit()
        logger.warning(
            "quota_tracker.suspended",
            reason=reason,
            suspended_at=ts,
        )

    def reset_suspension(self) -> None:
        """Clear the suspension flag. Manual operator action only."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE suspended SET active = 0, reason = NULL, suspended_at = NULL WHERE rowid = 1"
            )
            conn.commit()
        logger.info("quota_tracker.suspension_reset")

    def reset_daily(self, for_date: date | None = None) -> None:
        """Reset the request count to 0 for *for_date*. Called by Dagster at 00:00 UTC."""
        date_str = self._today_str(for_date)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quota_log (date, count) VALUES (?, 0) "
                "ON CONFLICT(date) DO UPDATE SET count = 0",
                (date_str,),
            )
            conn.commit()
        logger.info("quota_tracker.daily_reset", date=date_str)
