#!/usr/bin/env python3
"""Migrate SQLite databases to Aurora PostgreSQL (sub-fase 9.2).

Reads:
  data/governance.db     → lex_agents_app schema (feature_flags, kill_switches,
                           audit_trail, notifications, source_status,
                           prompt_evolution_proposals)
  data/consultations.db  → lex_agents_app.consultations, user_feedback, audit_samples

Writes to Aurora via asyncpg (DATABASE_URL or Secrets Manager).

Usage:
    # Dry run (print counts, no writes)
    python migrate_sqlite_to_aurora.py --dry-run

    # Full migration
    DATABASE_URL=postgresql+asyncpg://... python migrate_sqlite_to_aurora.py

    # AWS (reads from Secrets Manager)
    AWS_REGION=eu-west-1 LEX_ENV=dev python migrate_sqlite_to_aurora.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import boto3
import structlog

logging.basicConfig(level=logging.INFO)
log: structlog.BoundLogger = structlog.get_logger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _get_aurora_dsn() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Strip SQLAlchemy prefix if present
        return url.replace("postgresql+asyncpg://", "postgresql://")

    env = os.environ.get("LEX_ENV", "dev")
    region = os.environ.get("AWS_REGION", "eu-west-1")
    secret_name = f"/lex-agents/{env}/db/app-user"
    log.info("fetching_secret", secret=secret_name)

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    secret: dict[str, Any] = json.loads(response["SecretString"])

    host = secret["host"]
    port = secret.get("port", 5432)
    username = secret["username"]
    password = secret["password"]
    dbname = secret.get("dbname", "postgres")
    return f"postgresql://{username}:{password}@{host}:{port}/{dbname}"


def _sqlite_rows(db_path: Path, query: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def _parse_ts(val: str | None) -> datetime | None:
    """Parse ISO-8601 string from SQLite to datetime with UTC tz."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        log.warning("unparseable_timestamp", val=val)
        return None


# ---------------------------------------------------------------------------
# Per-table migration functions
# ---------------------------------------------------------------------------

async def migrate_feature_flags(conn: asyncpg.Connection, dry_run: bool) -> int:
    governance_db = DATA_DIR / "governance.db"
    if not governance_db.exists():
        log.warning("governance_db_not_found", path=str(governance_db))
        return 0

    rows = _sqlite_rows(governance_db, "SELECT key, value, updated_at, updated_by FROM feature_flags")
    log.info("feature_flags_found", count=len(rows))
    if dry_run or not rows:
        return len(rows)

    await conn.executemany(
        """
        INSERT INTO lex_agents_app.feature_flags (key, value, updated_at, updated_by)
        VALUES ($1, $2::jsonb, $3, $4)
        ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
        """,
        [(r["key"], r["value"], _parse_ts(r["updated_at"]) or datetime.now(UTC), r["updated_by"]) for r in rows],
    )
    return len(rows)


async def migrate_kill_switches(conn: asyncpg.Connection, dry_run: bool) -> int:
    governance_db = DATA_DIR / "governance.db"
    if not governance_db.exists():
        return 0

    rows = _sqlite_rows(governance_db, "SELECT target, engaged, engaged_at, engaged_by, reason FROM kill_switches")
    log.info("kill_switches_found", count=len(rows))
    if dry_run or not rows:
        return len(rows)

    await conn.executemany(
        """
        INSERT INTO lex_agents_app.kill_switches (target, engaged, engaged_at, actor, reason)
        VALUES ($1, $2::boolean, $3, $4, $5)
        ON CONFLICT (target) DO UPDATE
            SET engaged = EXCLUDED.engaged,
                engaged_at = EXCLUDED.engaged_at,
                actor = EXCLUDED.actor,
                reason = EXCLUDED.reason
        """,
        [(r["target"], bool(r["engaged"]), _parse_ts(r["engaged_at"]), r.get("engaged_by"), r.get("reason")) for r in rows],
    )
    return len(rows)


async def migrate_audit_trail(conn: asyncpg.Connection, dry_run: bool) -> int:
    governance_db = DATA_DIR / "governance.db"
    if not governance_db.exists():
        return 0

    rows = _sqlite_rows(
        governance_db,
        """SELECT timestamp, actor_user_id, actor_role, action_type, target_type,
                  target_id, before_state, after_state, reason, correlation_id,
                  checksum_prev, checksum_self
           FROM audit_trail ORDER BY id ASC""",
    )
    log.info("audit_trail_found", count=len(rows))
    if dry_run or not rows:
        return len(rows)

    # audit_trail is append-only; use raw execute to bypass triggers (migration only)
    # We temporarily disable triggers during migration, then re-enable
    await conn.execute("ALTER TABLE lex_agents_app.audit_trail DISABLE TRIGGER ALL")
    try:
        await conn.executemany(
            """
            INSERT INTO lex_agents_app.audit_trail
                (timestamp, actor_user_id, actor_role, action_type, target_type,
                 target_id, before_state, after_state, reason, correlation_id,
                 checksum_prev, checksum_self)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            [
                (
                    _parse_ts(r["timestamp"]) or datetime.now(UTC),
                    r["actor_user_id"], r["actor_role"], r["action_type"],
                    r["target_type"], r.get("target_id"), r.get("before_state"),
                    r.get("after_state"), r["reason"], r.get("correlation_id"),
                    r.get("checksum_prev"), r.get("checksum_self"),
                )
                for r in rows
            ],
        )
    finally:
        await conn.execute("ALTER TABLE lex_agents_app.audit_trail ENABLE TRIGGER ALL")

    log.info("audit_trail_migrated", count=len(rows))
    return len(rows)


async def migrate_notifications(conn: asyncpg.Connection, dry_run: bool) -> int:
    governance_db = DATA_DIR / "governance.db"
    if not governance_db.exists():
        return 0

    rows = _sqlite_rows(
        governance_db,
        "SELECT source, category, title, body, payload, correlation_id, created_at, read_at, read_by FROM notifications",
    )
    log.info("notifications_found", count=len(rows))
    if dry_run or not rows:
        return len(rows)

    await conn.executemany(
        """
        INSERT INTO lex_agents_app.notifications
            (source, category, title, body, payload, correlation_id, created_at, read_at, read_by)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)
        """,
        [
            (
                r["source"], r["category"], r["title"], r["body"],
                r.get("payload"), r.get("correlation_id"),
                _parse_ts(r["created_at"]) or datetime.now(UTC),
                _parse_ts(r.get("read_at")), r.get("read_by"),
            )
            for r in rows
        ],
    )
    return len(rows)


async def migrate_consultations(conn: asyncpg.Connection, dry_run: bool) -> int:
    consultations_db = DATA_DIR / "consultations.db"
    if not consultations_db.exists():
        log.warning("consultations_db_not_found", path=str(consultations_db))
        return 0

    rows = _sqlite_rows(
        consultations_db,
        """SELECT trace_id, created_at, query, response_json, verification_json,
                  prompt_versions, models, latency_ms, cost_estimate_usd
           FROM consultations ORDER BY created_at ASC""",
    )
    log.info("consultations_found", count=len(rows))
    if dry_run or not rows:
        return len(rows)

    def _parse_json(val: str | None) -> Any:
        if not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None

    await conn.executemany(
        """
        INSERT INTO lex_agents_app.consultations
            (trace_id, created_at, query, response_json, verification_json,
             prompt_versions, models, latency_ms, cost_estimate_usd)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
        ON CONFLICT (trace_id) DO NOTHING
        """,
        [
            (
                r["trace_id"],
                _parse_ts(r["created_at"]) or datetime.now(UTC),
                r["query"], r.get("response_json"), r.get("verification_json"),
                json.dumps(_parse_json(r.get("prompt_versions"))),
                json.dumps(_parse_json(r.get("models"))),
                r.get("latency_ms"), r.get("cost_estimate_usd"),
            )
            for r in rows
        ],
    )
    return len(rows)


async def migrate_user_feedback(conn: asyncpg.Connection, dry_run: bool) -> int:
    consultations_db = DATA_DIR / "consultations.db"
    if not consultations_db.exists():
        return 0

    rows = _sqlite_rows(
        consultations_db,
        "SELECT trace_id, verdict, notes, created_at FROM user_feedback ORDER BY id ASC",
    )
    log.info("user_feedback_found", count=len(rows))
    if dry_run or not rows:
        return len(rows)

    await conn.executemany(
        """
        INSERT INTO lex_agents_app.user_feedback (trace_id, verdict, notes, created_at)
        VALUES ($1, $2, $3, $4)
        """,
        [
            (r["trace_id"], r["verdict"], r.get("notes"), _parse_ts(r["created_at"]) or datetime.now(UTC))
            for r in rows
        ],
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(dry_run: bool) -> None:
    dsn = _get_aurora_dsn()
    if dry_run:
        log.info("dry_run_mode", message="No writes will be performed")

    conn = await asyncpg.connect(dsn)
    try:
        results: dict[str, int] = {}
        results["feature_flags"] = await migrate_feature_flags(conn, dry_run)
        results["kill_switches"] = await migrate_kill_switches(conn, dry_run)
        results["audit_trail"] = await migrate_audit_trail(conn, dry_run)
        results["notifications"] = await migrate_notifications(conn, dry_run)
        results["consultations"] = await migrate_consultations(conn, dry_run)
        results["user_feedback"] = await migrate_user_feedback(conn, dry_run)

        log.info("migration_complete", dry_run=dry_run, rows=results)

        if not dry_run:
            # Verify row counts match
            for table, expected in results.items():
                schema = "lex_agents_app"
                actual = await conn.fetchval(f"SELECT COUNT(*) FROM {schema}.{table}")
                if actual != expected:
                    log.error("row_count_mismatch", table=table, expected=expected, actual=actual)
                else:
                    log.info("row_count_ok", table=table, count=actual)
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite → Aurora PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing")
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
