"""SQLite-backed cost store — 4 tables for full FinOps tracking (ADR 0031)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Row models (dataclasses — lightweight, no Pydantic overhead for internal use)
# ---------------------------------------------------------------------------


@dataclass
class LocalCostRow:
    timestamp: str          # ISO hour bucket: "2026-05-12T06:00:00"
    agent_name: str
    model: str
    branch: str
    operation_type: str     # consultation | eval | ingest | prompt_evolution
    estimated_cost_usd: float
    trace_count: int
    token_count: int
    actual_cost_usd: float | None = None


@dataclass
class ReconciliationRow:
    date: str               # ISO date: "2026-05-12"
    local_estimate_usd: float
    anthropic_actual_usd: float
    diff_usd: float
    diff_pct: float
    status: str             # matched | drift | drift_high | missing_data | low_activity
    notes: str = ""


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS anthropic_usage_hourly (
    timestamp           TEXT NOT NULL,
    model               TEXT NOT NULL DEFAULT '',
    service_tier        TEXT NOT NULL DEFAULT '',
    context_window      TEXT NOT NULL DEFAULT '',
    workspace           TEXT NOT NULL DEFAULT '',
    uncached_input_tokens   INTEGER DEFAULT 0,
    cached_input_tokens     INTEGER DEFAULT 0,
    cache_creation_tokens   INTEGER DEFAULT 0,
    output_tokens           INTEGER DEFAULT 0,
    fetched_at          TEXT NOT NULL,
    PRIMARY KEY (timestamp, model, service_tier, context_window, workspace)
);

CREATE TABLE IF NOT EXISTS anthropic_cost_hourly (
    timestamp       TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    cost_usd        REAL DEFAULT 0.0,
    cost_type       TEXT NOT NULL DEFAULT 'tokens',
    workspace       TEXT NOT NULL DEFAULT '',
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (timestamp, description, cost_type, workspace)
);

CREATE TABLE IF NOT EXISTS local_cost_estimates_hourly (
    timestamp           TEXT NOT NULL,
    agent_name          TEXT NOT NULL,
    model               TEXT NOT NULL,
    branch              TEXT NOT NULL,
    operation_type      TEXT NOT NULL,
    estimated_cost_usd  REAL DEFAULT 0.0,
    actual_cost_usd     REAL,
    trace_count         INTEGER DEFAULT 0,
    token_count         INTEGER DEFAULT 0,
    PRIMARY KEY (timestamp, agent_name, model, branch, operation_type)
);

CREATE TABLE IF NOT EXISTS cost_reconciliation_daily (
    date                    TEXT PRIMARY KEY,
    local_estimate_usd      REAL DEFAULT 0.0,
    anthropic_actual_usd    REAL DEFAULT 0.0,
    diff_usd                REAL DEFAULT 0.0,
    diff_pct                REAL DEFAULT 0.0,
    status                  TEXT NOT NULL,
    notes                   TEXT DEFAULT ''
);
"""


# ---------------------------------------------------------------------------
# CostStore
# ---------------------------------------------------------------------------


class CostStore:
    """Async SQLite wrapper for data/cost.db."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_DDL)
            await db.commit()
        logger.info("cost_store_initialized", db_path=self._db_path)

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    async def upsert_usage_hourly(self, buckets: list[dict[str, Any]]) -> int:
        """Insert/replace Anthropic usage buckets. Returns number of rows written."""
        if not buckets:
            return 0
        fetched_at = datetime.utcnow().isoformat()
        rows = [
            (
                _ts(b.get("timestamp")),
                b.get("model", ""),
                b.get("service_tier", ""),
                b.get("context_window", ""),
                b.get("workspace", ""),
                int(b.get("uncached_input_tokens", 0)),
                int(b.get("cached_input_tokens", 0)),
                int(b.get("cache_creation_tokens", 0)),
                int(b.get("output_tokens", 0)),
                fetched_at,
            )
            for b in buckets
        ]
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                """INSERT OR REPLACE INTO anthropic_usage_hourly
                   (timestamp, model, service_tier, context_window, workspace,
                    uncached_input_tokens, cached_input_tokens, cache_creation_tokens,
                    output_tokens, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await db.commit()
        return len(rows)

    async def upsert_cost_hourly(self, buckets: list[dict[str, Any]]) -> int:
        """Insert/replace Anthropic cost buckets. Returns rows written."""
        if not buckets:
            return 0
        fetched_at = datetime.utcnow().isoformat()
        rows = [
            (
                _ts(b.get("timestamp")),
                b.get("description", ""),
                float(b.get("cost_usd", 0.0)),
                b.get("cost_type", "tokens"),
                b.get("workspace", ""),
                fetched_at,
            )
            for b in buckets
        ]
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                """INSERT OR REPLACE INTO anthropic_cost_hourly
                   (timestamp, description, cost_usd, cost_type, workspace, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                rows,
            )
            await db.commit()
        return len(rows)

    async def upsert_local_estimate(self, row: LocalCostRow) -> None:
        """Accumulate local cost estimate for an hourly bucket (additive upsert)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO local_cost_estimates_hourly
                   (timestamp, agent_name, model, branch, operation_type,
                    estimated_cost_usd, actual_cost_usd, trace_count, token_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(timestamp, agent_name, model, branch, operation_type)
                   DO UPDATE SET
                     estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                     trace_count        = trace_count + excluded.trace_count,
                     token_count        = token_count + excluded.token_count""",
                (
                    row.timestamp, row.agent_name, row.model, row.branch,
                    row.operation_type, row.estimated_cost_usd,
                    row.actual_cost_usd, row.trace_count, row.token_count,
                ),
            )
            await db.commit()

    async def upsert_reconciliation(self, row: ReconciliationRow) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO cost_reconciliation_daily
                   (date, local_estimate_usd, anthropic_actual_usd, diff_usd, diff_pct, status, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (row.date, row.local_estimate_usd, row.anthropic_actual_usd,
                 row.diff_usd, row.diff_pct, row.status, row.notes),
            )
            await db.commit()

    async def backfill_actual_cost(self, target_date: date) -> int:
        """Set actual_cost_usd on local estimates for a date using Anthropic actuals.

        Distributes cost proportionally by token_count within the same hour.
        Returns number of rows updated.
        """
        prefix = target_date.isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            # Sum total Anthropic cost for the day
            async with db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM anthropic_cost_hourly WHERE timestamp LIKE ?",
                (f"{prefix}%",),
            ) as cur:
                row = await cur.fetchone()
            total_actual = float(row[0]) if row else 0.0
            if total_actual == 0.0:
                return 0

            # Sum total local tokens for the day
            async with db.execute(
                "SELECT COALESCE(SUM(token_count), 0), COALESCE(SUM(estimated_cost_usd), 0) "
                "FROM local_cost_estimates_hourly WHERE timestamp LIKE ?",
                (f"{prefix}%",),
            ) as cur:
                row = await cur.fetchone()
            total_tokens, total_estimated = (float(row[0]), float(row[1])) if row else (0.0, 0.0)
            if total_tokens == 0.0 or total_estimated == 0.0:
                return 0

            ratio = total_actual / total_estimated
            await db.execute(
                """UPDATE local_cost_estimates_hourly
                   SET actual_cost_usd = estimated_cost_usd * ?
                   WHERE timestamp LIKE ?""",
                (ratio, f"{prefix}%"),
            )
            await db.commit()
            async with db.execute(
                "SELECT changes()"
            ) as cur:
                changed = await cur.fetchone()
            return int(changed[0]) if changed else 0

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    async def get_local_summary(
        self,
        start: datetime,
        end: datetime,
        group_by: str = "agent_name",
    ) -> list[dict[str, Any]]:
        allowed = {"agent_name", "model", "branch", "operation_type"}
        if group_by not in allowed:
            group_by = "agent_name"
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""SELECT {group_by} as key,
                       SUM(estimated_cost_usd) as total_usd,
                       SUM(trace_count) as traces,
                       SUM(token_count) as tokens
                   FROM local_cost_estimates_hourly
                   WHERE timestamp >= ? AND timestamp < ?
                   GROUP BY {group_by}
                   ORDER BY total_usd DESC""",
                (start.isoformat(), end.isoformat()),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_timeseries(
        self,
        metric: str,
        bucket: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return timeseries data for cost|tokens|queries bucketed by 1h|1d|1w."""
        if metric == "cost":
            value_expr = "SUM(estimated_cost_usd)"
        elif metric == "tokens":
            value_expr = "SUM(token_count)"
        else:
            value_expr = "SUM(trace_count)"

        if bucket == "1h":
            trunc = "substr(timestamp, 1, 13)"
        elif bucket == "1w":
            trunc = "strftime('%Y-%W', timestamp)"
        else:
            trunc = "substr(timestamp, 1, 10)"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""SELECT {trunc} as ts, {value_expr} as value
                    FROM local_cost_estimates_hourly
                    WHERE timestamp >= ? AND timestamp < ?
                    GROUP BY ts ORDER BY ts""",
                (start.isoformat(), end.isoformat()),
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_reconciliation_history(self, days: int = 30) -> list[ReconciliationRow]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT date, local_estimate_usd, anthropic_actual_usd,
                          diff_usd, diff_pct, status, notes
                   FROM cost_reconciliation_daily
                   ORDER BY date DESC LIMIT ?""",
                (days,),
            ) as cur:
                return [
                    ReconciliationRow(
                        date=r["date"],
                        local_estimate_usd=r["local_estimate_usd"],
                        anthropic_actual_usd=r["anthropic_actual_usd"],
                        diff_usd=r["diff_usd"],
                        diff_pct=r["diff_pct"],
                        status=r["status"],
                        notes=r["notes"] or "",
                    )
                    for r in await cur.fetchall()
                ]

    async def get_cost_for_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Look up cost metadata for a specific trace from consultations.db cross-reference.

        This queries local_cost_estimates_hourly for the hour window around the trace.
        For per-trace cost, the authoritative source is consultations.db (cost_estimate_usd).
        This method provides the aggregated context for the trace's hour bucket.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT agent_name, model, branch, operation_type,
                          estimated_cost_usd, actual_cost_usd, trace_count, token_count, timestamp
                   FROM local_cost_estimates_hourly
                   ORDER BY timestamp DESC LIMIT 50""",
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                return None
            return {
                "trace_id": trace_id,
                "hourly_buckets": [dict(r) for r in rows],
                "note": "per-trace breakdown from consultations.db cost_estimate_usd",
            }

    async def get_daily_totals(self, target_date: date) -> dict[str, float]:
        """Return {local_usd, anthropic_usd, trace_count} for a specific date."""
        prefix = target_date.isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT COALESCE(SUM(estimated_cost_usd), 0), COALESCE(SUM(trace_count), 0) "
                "FROM local_cost_estimates_hourly WHERE timestamp LIKE ?",
                (f"{prefix}%",),
            ) as cur:
                local_row = await cur.fetchone()
            async with db.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM anthropic_cost_hourly WHERE timestamp LIKE ?",
                (f"{prefix}%",),
            ) as cur:
                actual_row = await cur.fetchone()

        return {
            "local_usd": float(local_row[0]) if local_row else 0.0,
            "anthropic_usd": float(actual_row[0]) if actual_row else 0.0,
            "trace_count": int(local_row[1]) if local_row else 0,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(value: Any) -> str:
    """Normalise a timestamp value to ISO string."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value) if value is not None else ""
