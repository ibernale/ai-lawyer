"""FinOps assets — Anthropic cost sync and daily reconciliation.

Fetches hourly usage and cost data from the Anthropic Admin API, persists
it to a local SQLite database, and reconciles against local estimates.
"""

import os
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    Output,
    asset,
    asset_check,
)

logger = structlog.get_logger(__name__)

_DB_PATH = os.getenv("COST_DB_PATH", str(Path(__file__).parents[8] / "data" / "cost.db"))

_ANTHROPIC_BASE = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_RETRIES = 3
_RETRY_BACKOFF = 5  # seconds


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    db_path = Path(_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path))


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS anthropic_usage_hourly (
            timestamp TEXT,
            model TEXT,
            service_tier TEXT,
            context_window TEXT,
            workspace TEXT DEFAULT '',
            uncached_input_tokens INTEGER DEFAULT 0,
            cached_input_tokens INTEGER DEFAULT 0,
            cache_creation_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            fetched_at TEXT,
            PRIMARY KEY (timestamp, model, service_tier, context_window, workspace)
        );

        CREATE TABLE IF NOT EXISTS anthropic_cost_hourly (
            timestamp TEXT,
            description TEXT DEFAULT '',
            cost_usd REAL DEFAULT 0,
            cost_type TEXT DEFAULT 'tokens',
            workspace TEXT DEFAULT '',
            fetched_at TEXT,
            PRIMARY KEY (timestamp, description, cost_type, workspace)
        );

        CREATE TABLE IF NOT EXISTS cost_reconciliation_daily (
            date TEXT PRIMARY KEY,
            local_estimate_usd REAL,
            anthropic_actual_usd REAL,
            diff_usd REAL,
            diff_pct REAL,
            status TEXT,
            notes TEXT
        );
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Anthropic Admin API client
# ---------------------------------------------------------------------------


def _admin_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _get_with_retry(url: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """Synchronous GET with retry logic for 429 responses."""
    import httpx

    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params, headers=headers)

            if resp.status_code in (401, 403):
                raise PermissionError(f"Admin API auth error: {resp.status_code}")

            if resp.status_code == 429:
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "anthropic_admin_rate_limited",
                        attempt=attempt + 1,
                        backoff_seconds=_RETRY_BACKOFF,
                    )
                    time.sleep(_RETRY_BACKOFF)
                    continue
                raise RuntimeError("Admin API rate limit exceeded after retries")

            resp.raise_for_status()
            return resp.json()

        except PermissionError:
            raise
        except Exception as exc:
            if attempt < _MAX_RETRIES - 1:
                logger.warning("anthropic_admin_request_failed", attempt=attempt + 1, error=str(exc))
                time.sleep(_RETRY_BACKOFF)
            else:
                raise

    return {}


# ---------------------------------------------------------------------------
# Asset: anthropic_cost_sync
# ---------------------------------------------------------------------------


@asset(
    group_name="finops",
    compute_kind="admin_api",
    description="Fetches hourly usage and cost data from Anthropic Admin API into cost.db",
)
def anthropic_cost_sync(context: AssetExecutionContext) -> Output:
    admin_key = os.environ.get("ANTHROPIC_ADMIN_KEY", "")

    if not admin_key:
        logger.info("anthropic_cost_sync_skipped", reason="ANTHROPIC_ADMIN_KEY not set")
        return Output(
            {"rows_written": 0, "estimation_only": True},
            metadata={"estimation_only": True, "rows_usage": 0, "rows_cost": 0},
        )

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    fetched_at = datetime.now(UTC).isoformat()
    headers = _admin_headers(admin_key)

    # --- Fetch usage data ---
    usage_rows: list[dict[str, Any]] = []
    try:
        usage_data = _get_with_retry(
            f"{_ANTHROPIC_BASE}/usage",
            params={
                "start_date": yesterday,
                "end_date": today,
                "group_by[]": ["model", "service_tier", "context_window"],
                "bucket_width": "1h",
            },
            headers=headers,
        )
        usage_rows = usage_data.get("data", [])
    except PermissionError:
        logger.warning("admin_key_invalid", endpoint="usage")
        return Output(
            {"rows_written": 0, "estimation_only": True},
            metadata={"estimation_only": True, "rows_usage": 0, "rows_cost": 0},
        )
    except Exception as exc:
        logger.warning("anthropic_usage_fetch_failed", error=str(exc))
        usage_rows = []

    # --- Fetch cost data ---
    cost_rows: list[dict[str, Any]] = []
    try:
        cost_data = _get_with_retry(
            f"{_ANTHROPIC_BASE}/costs",
            params={
                "start_date": yesterday,
                "end_date": today,
                "group_by[]": ["description"],
                "bucket_width": "1h",
            },
            headers=headers,
        )
        cost_rows = cost_data.get("data", [])
    except PermissionError:
        logger.warning("admin_key_invalid", endpoint="costs")
        return Output(
            {"rows_written": 0, "estimation_only": True},
            metadata={"estimation_only": True, "rows_usage": 0, "rows_cost": 0},
        )
    except Exception as exc:
        logger.warning("anthropic_cost_fetch_failed", error=str(exc))
        cost_rows = []

    # --- Persist to SQLite ---
    conn = _get_conn()
    try:
        _ensure_tables(conn)

        rows_usage = 0
        for row in usage_rows:
            ts = row.get("timestamp", "")
            model = row.get("model", "")
            service_tier = row.get("service_tier", "")
            context_window = str(row.get("context_window", ""))
            workspace = row.get("workspace", "")
            conn.execute(
                """
                INSERT OR REPLACE INTO anthropic_usage_hourly
                    (timestamp, model, service_tier, context_window, workspace,
                     uncached_input_tokens, cached_input_tokens, cache_creation_tokens,
                     output_tokens, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    model,
                    service_tier,
                    context_window,
                    workspace,
                    row.get("uncached_input_tokens", 0),
                    row.get("cached_input_tokens", 0),
                    row.get("cache_creation_tokens", 0),
                    row.get("output_tokens", 0),
                    fetched_at,
                ),
            )
            rows_usage += 1

        rows_cost = 0
        for row in cost_rows:
            ts = row.get("timestamp", "")
            description = row.get("description", "")
            cost_usd = float(row.get("cost_usd", 0) or 0)
            cost_type = row.get("cost_type", "tokens")
            workspace = row.get("workspace", "")
            conn.execute(
                """
                INSERT OR REPLACE INTO anthropic_cost_hourly
                    (timestamp, description, cost_usd, cost_type, workspace, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts, description, cost_usd, cost_type, workspace, fetched_at),
            )
            rows_cost += 1

        conn.commit()
    finally:
        conn.close()

    context.log.info(
        "anthropic_cost_sync_done",
        rows_usage=rows_usage,
        rows_cost=rows_cost,
        date_synced=yesterday,
    )

    return Output(
        {
            "rows_usage": rows_usage,
            "rows_cost": rows_cost,
            "date_synced": yesterday,
            "estimation_only": False,
        },
        metadata={
            "rows_usage": rows_usage,
            "rows_cost": rows_cost,
            "date_synced": yesterday,
            "estimation_only": False,
        },
    )


# ---------------------------------------------------------------------------
# Asset: cost_reconciliation_daily
# ---------------------------------------------------------------------------


@asset(
    group_name="finops",
    compute_kind="reconciliation",
    deps=[anthropic_cost_sync],
    description="Reconciles local cost estimates against Anthropic actual charges for yesterday",
)
def cost_reconciliation_daily(context: AssetExecutionContext) -> Output:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    conn = _get_conn()
    try:
        _ensure_tables(conn)

        # --- Local estimate ---
        local_estimate: float | None = None
        trace_count: int = 0
        try:
            row = conn.execute(
                """
                SELECT SUM(estimated_cost_usd), COUNT(*)
                FROM local_cost_estimates_hourly
                WHERE timestamp LIKE ?
                """,
                (f"{yesterday}%",),
            ).fetchone()
            if row and row[0] is not None:
                local_estimate = float(row[0])
                trace_count = int(row[1] or 0)
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            local_estimate = None
            trace_count = 0

        # --- Anthropic actual ---
        anthropic_actual: float | None = None
        try:
            row = conn.execute(
                """
                SELECT SUM(cost_usd)
                FROM anthropic_cost_hourly
                WHERE timestamp LIKE ?
                """,
                (f"{yesterday}%",),
            ).fetchone()
            if row and row[0] is not None:
                anthropic_actual = float(row[0])
        except sqlite3.OperationalError:
            anthropic_actual = None

        # --- Determine status ---
        status: str
        notes: str
        diff_usd = 0.0
        diff_pct = 0.0

        if local_estimate is None or anthropic_actual is None:
            status = "missing_data"
            notes = (
                f"local_estimate={'N/A' if local_estimate is None else local_estimate:.4f}, "
                f"anthropic_actual={'N/A' if anthropic_actual is None else anthropic_actual:.4f}"
            )
        elif trace_count < 10:
            status = "low_activity"
            notes = f"trace_count={trace_count} < 10 minimum threshold"
        else:
            diff_usd = anthropic_actual - local_estimate
            diff_pct = abs(diff_usd / anthropic_actual) * 100 if anthropic_actual > 0 else 0.0

            if diff_pct <= 5.0:
                status = "matched"
                notes = f"diff={diff_pct:.2f}% within 5% threshold"
            elif diff_pct <= 20.0:
                status = "drift"
                notes = f"diff={diff_pct:.2f}% between 5-20% thresholds"
                context.log.warning(
                    "cost_reconciliation_drift",
                    date=yesterday,
                    diff_usd=round(diff_usd, 4),
                    diff_pct=round(diff_pct, 2),
                    local_estimate=round(local_estimate, 4),
                    anthropic_actual=round(anthropic_actual, 4),
                )
            else:
                status = "drift_high"
                notes = f"diff={diff_pct:.2f}% exceeds 20% threshold"
                context.log.critical(
                    "cost_reconciliation_drift_high",
                    date=yesterday,
                    diff_usd=round(diff_usd, 4),
                    diff_pct=round(diff_pct, 2),
                    local_estimate=round(local_estimate, 4),
                    anthropic_actual=round(anthropic_actual, 4),
                )

        # --- Upsert reconciliation record ---
        conn.execute(
            """
            INSERT OR REPLACE INTO cost_reconciliation_daily
                (date, local_estimate_usd, anthropic_actual_usd, diff_usd, diff_pct, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                yesterday,
                local_estimate,
                anthropic_actual,
                round(diff_usd, 6),
                round(diff_pct, 4),
                status,
                notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    context.log.info(
        "cost_reconciliation_done",
        date=yesterday,
        status=status,
        diff_usd=round(diff_usd, 4),
        diff_pct=round(diff_pct, 2),
    )

    return Output(
        {
            "date": yesterday,
            "local_estimate_usd": local_estimate,
            "anthropic_actual_usd": anthropic_actual,
            "diff_usd": round(diff_usd, 6),
            "diff_pct": round(diff_pct, 4),
            "status": status,
            "notes": notes,
        },
        metadata={
            "date": yesterday,
            "local_estimate_usd": local_estimate if local_estimate is not None else 0.0,
            "anthropic_actual_usd": anthropic_actual if anthropic_actual is not None else 0.0,
            "diff_usd": round(diff_usd, 6),
            "diff_pct": round(diff_pct, 4),
            "status": status,
        },
    )


# ---------------------------------------------------------------------------
# Asset checks on anthropic_cost_sync
# ---------------------------------------------------------------------------


@asset_check(
    asset=anthropic_cost_sync,
    description="Usage report must not be empty if API key is configured",
)
def usage_report_not_empty(context: AssetExecutionContext) -> AssetCheckResult:
    admin_key = os.environ.get("ANTHROPIC_ADMIN_KEY", "")
    if not admin_key:
        return AssetCheckResult(
            passed=True,
            description="No ANTHROPIC_ADMIN_KEY configured — estimation_only mode, skipping check",
        )

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = _get_conn()
    try:
        _ensure_tables(conn)
        row = conn.execute(
            "SELECT COUNT(*) FROM anthropic_usage_hourly WHERE timestamp LIKE ?",
            (f"{yesterday}%",),
        ).fetchone()
        count = int(row[0]) if row else 0
    except sqlite3.OperationalError:
        count = 0
    finally:
        conn.close()

    if count > 0:
        return AssetCheckResult(
            passed=True,
            description=f"Usage report has {count} row(s) for {yesterday}",
        )

    return AssetCheckResult(
        passed=False,
        severity=AssetCheckSeverity.WARN,
        description=f"No usage rows found for {yesterday} despite API key being set",
    )


@asset_check(
    asset=anthropic_cost_sync,
    description="Cost report must show positive spend if local estimates exist",
)
def cost_positive_if_local_active(context: AssetExecutionContext) -> AssetCheckResult:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = _get_conn()
    try:
        _ensure_tables(conn)

        # Check local estimates
        local_sum: float = 0.0
        try:
            row = conn.execute(
                """
                SELECT SUM(estimated_cost_usd)
                FROM local_cost_estimates_hourly
                WHERE timestamp LIKE ? AND estimated_cost_usd > 0
                """,
                (f"{yesterday}%",),
            ).fetchone()
            local_sum = float(row[0] or 0) if row and row[0] is not None else 0.0
        except sqlite3.OperationalError:
            local_sum = 0.0

        if local_sum <= 0:
            return AssetCheckResult(
                passed=True,
                description=f"No local cost estimates for {yesterday} — nothing to cross-check",
            )

        # Check Anthropic actuals
        actual_count: int = 0
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM anthropic_cost_hourly WHERE timestamp LIKE ?",
                (f"{yesterday}%",),
            ).fetchone()
            actual_count = int(row[0]) if row else 0
        except sqlite3.OperationalError:
            actual_count = 0

        if actual_count > 0:
            return AssetCheckResult(
                passed=True,
                description=(
                    f"Local estimates={local_sum:.4f} USD and {actual_count} Anthropic cost row(s) "
                    f"both present for {yesterday}"
                ),
            )

        return AssetCheckResult(
            passed=False,
            severity=AssetCheckSeverity.WARN,
            description=(
                f"Local estimates={local_sum:.4f} USD for {yesterday} but Anthropic cost table is "
                "empty — possible untracked API calls or Admin API key issue"
            ),
        )
    finally:
        conn.close()
