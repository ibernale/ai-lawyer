"""ContractStore — dual-mode: Aurora (asyncpg) or SQLite (aiosqlite).

Mode selection mirrors the pattern in lex_agents_api.db:
  - DATABASE_URL set → asyncpg (Aurora Serverless v2 / lex_agents_app schema)
  - DATABASE_URL not set → aiosqlite (local dev, data/contracts.db)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from lex_agents_shared.db import is_postgres, pg_conn

from lex_agents_agents.contracts.models import ContractAnalysis

logger: structlog.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQLite DDL (local dev only)
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS contracts (
    contract_id          TEXT PRIMARY KEY,
    trace_id             TEXT UNIQUE NOT NULL,
    created_at           TEXT NOT NULL,
    filename             TEXT NOT NULL,
    document_type        TEXT,
    overall_risk_score   REAL,
    overall_risk_rating  TEXT,
    analysis_json        TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    latency_ms           INTEGER,
    cost_estimate_usd    REAL,
    error_message        TEXT
)
"""


# ---------------------------------------------------------------------------
# ContractStore
# ---------------------------------------------------------------------------


class ContractStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        if is_postgres():
            # Schema managed by Alembic migration 0005 — nothing to create here.
            logger.info("contract_store_postgres_mode")
            return
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE)
            await db.commit()
        logger.info("contract_store_initialized", db_path=self._db_path)

    async def save(
        self, analysis: ContractAnalysis, *, tenant_id: str = "default"
    ) -> None:
        if is_postgres():
            await self._pg_save(analysis, tenant_id=tenant_id)
        else:
            await self._sqlite_save(analysis)

    async def get(
        self, contract_id: str, *, tenant_id: str = "default"
    ) -> ContractAnalysis | None:
        if is_postgres():
            return await self._pg_get(contract_id, tenant_id=tenant_id)
        return await self._sqlite_get(contract_id)

    async def list_recent(
        self, limit: int = 20, *, tenant_id: str = "default"
    ) -> list[ContractAnalysis]:
        if is_postgres():
            return await self._pg_list_recent(limit, tenant_id=tenant_id)
        return await self._sqlite_list_recent(limit)

    async def update_status(
        self,
        contract_id: str,
        status: str,
        *,
        error: str | None = None,
        tenant_id: str = "default",
    ) -> None:
        if is_postgres():
            await self._pg_update_status(contract_id, status, error=error, tenant_id=tenant_id)
        else:
            await self._sqlite_update_status(contract_id, status, error=error)

    # ------------------------------------------------------------------
    # PostgreSQL (asyncpg)
    # ------------------------------------------------------------------

    async def _pg_save(
        self, analysis: ContractAnalysis, *, tenant_id: str = "default"
    ) -> None:
        metadata = analysis.metadata
        risk = analysis.risk_assessment
        async with pg_conn(tenant_id) as conn:
            await conn.execute(
                """
                INSERT INTO contracts (
                    contract_id, trace_id, created_at, filename,
                    document_type, parties, jurisdiction, governing_law,
                    applicable_framework, overall_risk_score, overall_risk_rating,
                    analysis_json, status, latency_ms, cost_estimate_usd
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9::jsonb,
                        $10, $11, $12::jsonb, 'complete', $13, $14)
                ON CONFLICT (contract_id) DO UPDATE
                    SET trace_id             = EXCLUDED.trace_id,
                        filename             = EXCLUDED.filename,
                        document_type        = EXCLUDED.document_type,
                        parties              = EXCLUDED.parties,
                        jurisdiction         = EXCLUDED.jurisdiction,
                        governing_law        = EXCLUDED.governing_law,
                        applicable_framework = EXCLUDED.applicable_framework,
                        overall_risk_score   = EXCLUDED.overall_risk_score,
                        overall_risk_rating  = EXCLUDED.overall_risk_rating,
                        analysis_json        = EXCLUDED.analysis_json,
                        status               = EXCLUDED.status,
                        latency_ms           = EXCLUDED.latency_ms,
                        cost_estimate_usd    = EXCLUDED.cost_estimate_usd,
                        error_message        = NULL
                """,
                analysis.contract_id,
                analysis.trace_id,
                datetime.now(UTC),
                analysis.filename,
                metadata.document_type,
                json.dumps([p.model_dump() for p in metadata.parties]),
                json.dumps(metadata.jurisdiction),
                metadata.governing_law,
                json.dumps(metadata.applicable_framework),
                risk.overall_score,
                risk.overall_rating,
                analysis.model_dump_json(),
                analysis.latency_ms,
                analysis.cost_estimate_usd,
            )
        logger.debug("contract_saved_pg", contract_id=analysis.contract_id, tenant_id=tenant_id)

    async def _pg_get(
        self, contract_id: str, *, tenant_id: str = "default"
    ) -> ContractAnalysis | None:
        async with pg_conn(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT analysis_json FROM contracts WHERE contract_id = $1", contract_id
            )
        if row is None:
            return None
        return _parse_analysis_json(row["analysis_json"])

    async def _pg_list_recent(
        self, limit: int, *, tenant_id: str = "default"
    ) -> list[ContractAnalysis]:
        async with pg_conn(tenant_id) as conn:
            rows = await conn.fetch(
                "SELECT analysis_json FROM contracts"
                " WHERE status = 'complete'"
                " ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        results: list[ContractAnalysis] = []
        for row in rows:
            analysis = _parse_analysis_json(row["analysis_json"])
            if analysis is not None:
                results.append(analysis)
        return results

    async def _pg_update_status(
        self,
        contract_id: str,
        status: str,
        *,
        error: str | None = None,
        tenant_id: str = "default",
    ) -> None:
        async with pg_conn(tenant_id) as conn:
            await conn.execute(
                """
                UPDATE contracts
                SET status = $1, error_message = $2
                WHERE contract_id = $3
                """,
                status,
                error,
                contract_id,
            )
        logger.debug(
            "contract_status_updated_pg",
            contract_id=contract_id,
            status=status,
            tenant_id=tenant_id,
        )

    # ------------------------------------------------------------------
    # SQLite (aiosqlite) — local dev
    # ------------------------------------------------------------------

    async def _sqlite_save(self, analysis: ContractAnalysis) -> None:
        import aiosqlite

        metadata = analysis.metadata
        risk = analysis.risk_assessment
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO contracts (
                    contract_id, trace_id, created_at, filename,
                    document_type, overall_risk_score, overall_risk_rating,
                    analysis_json, status, latency_ms, cost_estimate_usd
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'complete', ?, ?)
                """,
                (
                    analysis.contract_id,
                    analysis.trace_id,
                    datetime.now(UTC).isoformat(),
                    analysis.filename,
                    metadata.document_type,
                    risk.overall_score,
                    risk.overall_rating,
                    analysis.model_dump_json(),
                    analysis.latency_ms,
                    analysis.cost_estimate_usd,
                ),
            )
            await db.commit()
        logger.debug("contract_saved", contract_id=analysis.contract_id)

    async def _sqlite_get(self, contract_id: str) -> ContractAnalysis | None:
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT analysis_json FROM contracts WHERE contract_id = ?",
                (contract_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return _parse_analysis_json(row["analysis_json"])

    async def _sqlite_list_recent(self, limit: int) -> list[ContractAnalysis]:
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT analysis_json FROM contracts"
                " WHERE status = 'complete'"
                " ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        results: list[ContractAnalysis] = []
        for row in rows:
            analysis = _parse_analysis_json(row["analysis_json"])
            if analysis is not None:
                results.append(analysis)
        return results

    async def _sqlite_update_status(
        self, contract_id: str, status: str, *, error: str | None = None
    ) -> None:
        import aiosqlite

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE contracts SET status = ?, error_message = ? WHERE contract_id = ?",
                (status, error, contract_id),
            )
            await db.commit()
        logger.debug("contract_status_updated", contract_id=contract_id, status=status)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_analysis_json(raw: Any) -> ContractAnalysis | None:
    """Parse a JSON string or dict into ContractAnalysis; returns None on failure."""
    try:
        if isinstance(raw, str):
            data: dict[str, Any] = json.loads(raw)
        elif isinstance(raw, dict):
            data = raw
        else:
            return None
        return ContractAnalysis.model_validate(data)
    except Exception as exc:
        logger.warning("contract_parse_failed", error=str(exc))
        return None
