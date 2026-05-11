# ADR 0007 — Consultation History Storage

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** lex-agents team

## Context

The `/api/v1/consult` endpoint must persist each consultation (query, response, verification
report, prompt versions, latency, cost) to support:
- Audit trail for legal compliance
- `GET /api/v1/consult/{trace_id}` retrieval
- Historical overview at `/historico`

We need persistence that is simple to operate in MVP, available without infrastructure provisioning,
and non-blocking to the async FastAPI event loop.

## Decision

Use **SQLite** via `aiosqlite` for consultation history.

**Schema** (`data/consultations.db`):
```sql
CREATE TABLE consultations (
    trace_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    query TEXT NOT NULL,
    response_json TEXT NOT NULL,
    verification_json TEXT,
    prompt_versions TEXT,      -- JSON dict
    models TEXT,               -- JSON list
    latency_ms INTEGER,
    cost_estimate_usd REAL
);
```

The full `ConsultResponse` is stored as JSON in `response_json`. This allows schema evolution
without migrations: new fields appear in JSON without requiring `ALTER TABLE`.

`data/` is already gitignored. The store creates the file and table automatically on startup.

## Consequences

**Benefits:**
- Zero infrastructure: no separate DB process, no Docker service, no connection pooling
- `aiosqlite` wraps SQLite in a thread pool executor — non-blocking for uvicorn's event loop
- Single-file backup: `cp data/consultations.db backup.db`
- `make db-show` for quick CLI inspection

**Limitations:**
- No concurrent writes across multiple API replicas (WAL mode could help, but we have 1 replica in MVP)
- No row-level security or multi-tenant isolation
- Queries are simple (by trace_id, ordered by date) — no need for a query planner

## Alternatives rejected

| Option | Reason for rejection |
|--------|---------------------|
| PostgreSQL | Requires Docker service, connection pool, migrations — overkill for MVP |
| Redis | Volatile without RDB snapshots; poor fit for structured query/response pairs |
| File-per-consultation (JSON) | No query capability, hard to list/sort |
| In-memory (no persistence) | Audit trail requirement rules this out |

## Migration path

Fase 5/6: if multi-tenancy or horizontal scaling is required, migrate to PostgreSQL using
Alembic. The `response_json` column maps 1:1 to the Pydantic model — no transformation needed.
