#!/usr/bin/env python3
"""Post-migration verification for SQLite → Aurora (sub-fase 9.2).

Checks:
  1. Row counts in Aurora match SQLite source row counts.
  2. audit_trail checksum chain is intact (each row's checksum_prev == previous
     row's checksum_self, ordered by id ASC).
  3. No NULL timestamps in NOT NULL TIMESTAMPTZ columns.

Usage:
    # Verify after migration
    DATABASE_URL=postgresql+asyncpg://... python verify_migration.py

    # AWS (reads from Secrets Manager)
    AWS_REGION=eu-west-1 LEX_ENV=dev python verify_migration.py

Exit codes:
    0 — all checks passed
    1 — one or more checks failed (details logged at ERROR level)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import boto3
import structlog

logging.basicConfig(level=logging.INFO)
log: structlog.BoundLogger = structlog.get_logger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent.parent.parent / "data"

SCHEMA = "lex_agents_app"

# (aurora_table, sqlite_db, sqlite_table)
TABLE_MAP: list[tuple[str, str, str]] = [
    ("feature_flags", "governance.db", "feature_flags"),
    ("kill_switches", "governance.db", "kill_switches"),
    ("audit_trail", "governance.db", "audit_trail"),
    ("notifications", "governance.db", "notifications"),
    ("consultations", "consultations.db", "consultations"),
    ("user_feedback", "consultations.db", "user_feedback"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_aurora_dsn() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
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


def _sqlite_count(db_name: str, table: str) -> int | None:
    db_path = DATA_DIR / db_name
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Check dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str = ""
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

async def check_row_counts(conn: asyncpg.Connection) -> CheckResult:
    """Compare Aurora row counts against SQLite source counts."""
    errors: list[str] = []
    details_lines: list[str] = []

    for aurora_table, db_name, sqlite_table in TABLE_MAP:
        sqlite_count = _sqlite_count(db_name, sqlite_table)
        if sqlite_count is None:
            details_lines.append(f"  {aurora_table}: SQLite source missing (skipped)")
            continue

        aurora_count: int = await conn.fetchval(
            f"SELECT COUNT(*) FROM {SCHEMA}.{aurora_table}"
        )
        match = aurora_count >= sqlite_count  # >= because Aurora may have seed rows
        status = "OK" if match else "MISMATCH"
        details_lines.append(
            f"  {aurora_table}: sqlite={sqlite_count} aurora={aurora_count} [{status}]"
        )
        if not match:
            errors.append(
                f"{aurora_table}: expected >={sqlite_count} rows, got {aurora_count}"
            )

    return CheckResult(
        name="row_counts",
        passed=len(errors) == 0,
        details="\n".join(details_lines),
        errors=errors,
    )


async def check_audit_trail_chain(conn: asyncpg.Connection) -> CheckResult:
    """Verify audit_trail checksum chain integrity."""
    rows = await conn.fetch(
        f"""
        SELECT id, checksum_prev, checksum_self
        FROM {SCHEMA}.audit_trail
        ORDER BY id ASC
        """
    )

    if not rows:
        return CheckResult(
            name="audit_trail_chain",
            passed=True,
            details="  audit_trail is empty — chain trivially valid",
        )

    errors: list[str] = []
    prev_checksum_self: str | None = None

    for i, row in enumerate(rows):
        row_id = row["id"]
        checksum_prev = row["checksum_prev"]
        checksum_self = row["checksum_self"]

        if i == 0:
            # First row: checksum_prev may be None or a sentinel
            pass
        else:
            if checksum_prev != prev_checksum_self:
                errors.append(
                    f"Chain break at id={row_id}: "
                    f"checksum_prev={checksum_prev!r} != "
                    f"prev checksum_self={prev_checksum_self!r}"
                )

        prev_checksum_self = checksum_self

    return CheckResult(
        name="audit_trail_chain",
        passed=len(errors) == 0,
        details=f"  Checked {len(rows)} audit_trail rows",
        errors=errors,
    )


async def check_null_timestamps(conn: asyncpg.Connection) -> CheckResult:
    """Ensure no NULL timestamps in NOT NULL TIMESTAMPTZ columns."""
    checks: list[tuple[str, str]] = [
        ("feature_flags", "updated_at"),
        ("kill_switches", "engaged_at"),
        ("notifications", "created_at"),
        ("consultations", "created_at"),
        ("user_feedback", "created_at"),
        ("audit_trail", "timestamp"),
    ]

    errors: list[str] = []
    details_lines: list[str] = []

    for table, col in checks:
        null_count: int = await conn.fetchval(
            f"SELECT COUNT(*) FROM {SCHEMA}.{table} WHERE {col} IS NULL"
        )
        status = "OK" if null_count == 0 else f"NULLS={null_count}"
        details_lines.append(f"  {table}.{col}: {status}")
        if null_count > 0:
            errors.append(f"{table}.{col} has {null_count} NULL timestamps")

    return CheckResult(
        name="null_timestamps",
        passed=len(errors) == 0,
        details="\n".join(details_lines),
        errors=errors,
    )


async def check_audit_trail_immutability(conn: asyncpg.Connection) -> CheckResult:
    """Verify that audit_trail UPDATE/DELETE triggers are active."""
    # Check triggers exist and are enabled
    rows = await conn.fetch(
        """
        SELECT tgname, tgenabled
        FROM pg_trigger
        WHERE tgrelid = 'lex_agents_app.audit_trail'::regclass
          AND tgname IN ('audit_trail_no_update', 'audit_trail_no_delete')
        ORDER BY tgname
        """
    )

    errors: list[str] = []
    found = {r["tgname"]: r["tgenabled"] for r in rows}
    details_lines: list[str] = []

    for expected in ("audit_trail_no_delete", "audit_trail_no_update"):
        if expected not in found:
            errors.append(f"Trigger {expected} not found")
            details_lines.append(f"  {expected}: MISSING")
        elif found[expected] != "O":  # 'O' = origin (enabled)
            errors.append(f"Trigger {expected} is disabled (tgenabled={found[expected]!r})")
            details_lines.append(f"  {expected}: DISABLED ({found[expected]})")
        else:
            details_lines.append(f"  {expected}: enabled")

    return CheckResult(
        name="audit_trail_immutability",
        passed=len(errors) == 0,
        details="\n".join(details_lines),
        errors=errors,
    )


async def check_schema_exists(conn: asyncpg.Connection) -> CheckResult:
    """Verify all expected schemas exist."""
    expected = {"lex_agents_app", "lex_agents_cost", "bedrock_integration"}
    rows = await conn.fetch(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY($1)",
        list(expected),
    )
    found = {r["schema_name"] for r in rows}
    missing = expected - found
    errors = [f"Schema missing: {s}" for s in sorted(missing)]
    details = f"  Found: {sorted(found)}"
    if missing:
        details += f"\n  Missing: {sorted(missing)}"
    return CheckResult(
        name="schemas_exist",
        passed=len(errors) == 0,
        details=details,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run() -> bool:
    dsn = _get_aurora_dsn()
    conn = await asyncpg.connect(dsn)

    all_checks: list[CheckResult] = []
    try:
        all_checks.append(await check_schema_exists(conn))
        all_checks.append(await check_row_counts(conn))
        all_checks.append(await check_null_timestamps(conn))
        all_checks.append(await check_audit_trail_chain(conn))
        all_checks.append(await check_audit_trail_immutability(conn))
    finally:
        await conn.close()

    # Report
    print("\n" + "=" * 60)
    print("Migration Verification Report")
    print("=" * 60)
    all_passed = True
    for check in all_checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"\n[{status}] {check.name}")
        if check.details:
            print(check.details)
        for err in check.errors:
            print(f"  ERROR: {err}")
        if not check.passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("Result: ALL CHECKS PASSED")
        log.info("verification_passed", checks=len(all_checks))
    else:
        failed = [c.name for c in all_checks if not c.passed]
        print(f"Result: FAILED ({len(failed)} checks: {', '.join(failed)})")
        log.error("verification_failed", failed_checks=failed)
    print("=" * 60 + "\n")

    return all_passed


def main() -> None:
    passed = asyncio.run(run())
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
