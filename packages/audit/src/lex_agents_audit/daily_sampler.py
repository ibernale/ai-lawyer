"""Daily audit sampler — selects 5 responses/day stratified by branch and depth."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite
import structlog

from lex_agents_audit.audit_store import AuditSampleRecord, AuditStore

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_SAMPLES_PER_DAY = 5


async def run_daily_sample(
    consultation_db_path: str,
    audit_store: AuditStore,
    reference_dt: datetime | None = None,
) -> list[AuditSampleRecord]:
    """Sample up to 5 consultations from the last 24 hours, stratified by branch+depth.

    Idempotent: if today's samples already exist they are not duplicated.
    reference_dt defaults to utcnow (injectable for testing).
    """
    now = reference_dt or datetime.now(UTC)
    cutoff = (now - timedelta(hours=24)).isoformat()

    already_sampled = await _get_already_sampled_today(audit_store, now)

    async with aiosqlite.connect(consultation_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT trace_id, query, response_json, created_at FROM consultations WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ) as cursor:
            rows = await cursor.fetchall()

    candidates = [r for r in rows if r["trace_id"] not in already_sampled]
    if not candidates:
        logger.info("daily_sampler_no_candidates", cutoff=cutoff)
        return []

    # Build stratified pools: group by (branch, depth)
    pools: dict[tuple[str, str], list[Any]] = {}
    for row in candidates:
        try:
            data: dict[str, Any] = json.loads(row["response_json"])
        except Exception:
            logger.debug("daily_sampler_skip_bad_json", trace_id=row["trace_id"])
            continue
        branch = str(data.get("routing", {}).get("branch", "unknown"))
        depth = str(data.get("depth_used", "standard"))
        key = (branch, depth)
        pools.setdefault(key, []).append(row)

    # Round-robin over strata to pick samples
    selected: list[Any] = []
    strata = list(pools.keys())
    random.shuffle(strata)
    i = 0
    while len(selected) < _SAMPLES_PER_DAY and i < len(candidates):
        key = strata[i % len(strata)]
        pool = pools.get(key, [])
        if pool:
            chosen = random.choice(pool)  # noqa: S311 — non-crypto sampling
            selected.append(chosen)
            pool.remove(chosen)
        i += 1

    saved: list[AuditSampleRecord] = []
    for row in selected:
        try:
            data = json.loads(row["response_json"])
        except Exception:
            data = {}
        record = AuditSampleRecord(
            trace_id=row["trace_id"],
            query=row["query"],
            response_json=row["response_json"],
            branch=str(data.get("routing", {}).get("branch", "unknown")),
            depth=str(data.get("depth_used", "standard")),
            sampled_at=now,
        )
        await audit_store.save(record)
        saved.append(record)

    logger.info(
        "daily_sampler_done",
        n_candidates=len(candidates),
        n_sampled=len(saved),
        date=now.date().isoformat(),
    )
    return saved


async def _get_already_sampled_today(store: AuditStore, now: datetime) -> set[str]:
    """Return trace_ids already sampled today to avoid duplicates."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    async with aiosqlite.connect(store._db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT trace_id FROM audit_samples WHERE sampled_at >= ?",
            (today_start,),
        ) as cursor:
            rows = await cursor.fetchall()
    return {r["trace_id"] for r in rows}
