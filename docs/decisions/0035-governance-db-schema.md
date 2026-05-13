# ADR-0035: Governance DB Schema (governance.db)

**Status:** Accepted  
**Date:** 2026-04-20  
**Fase:** 8.4–8.5

---

## Context

Fase 8 introduced multiple operational subsystems, each needing persistent state:
- Kill switches and feature flags (ADR-0032)
- Source governance (pause/resume)
- Prompt evolution proposals
- Immutable audit trail (ADR-0034)
- In-app notifications (Fase 8.5)

The question is whether to use one database file or multiple.

---

## Decision

**All governance state lives in a single SQLite file: `governance.db`.**

Tables and their owning managers:

| Table              | Manager                  | Package             |
|--------------------|--------------------------|---------------------|
| `kill_switches`    | `SystemStateManager`     | `lex_agents_admin`  |
| `feature_flags`    | `SystemStateManager`     | `lex_agents_admin`  |
| `source_status`    | `GovernanceManager`      | `lex_agents_admin`  |
| `proposals`        | `GovernanceManager`      | `lex_agents_admin`  |
| `audit_trail`      | `AuditTrailManager`      | `lex_agents_audit`  |
| `notifications`    | `NotificationManager`    | `lex_agents_audit`  |

All managers are initialized in `lifespan()` in `main.py` with
`settings.governance_db_path` (default: `data/governance.db`).
Each manager's `init()` method creates its tables with `CREATE TABLE IF NOT EXISTS`
and is idempotent on repeated startup.

**Consultation data** (consultation history, feedback, audit samples) remains in
`consultations.db` (ADR-0007). The separation keeps operational governance state
distinct from user-generated content and simplifies backup granularity.

---

## Alternatives considered

**One SQLite file per subsystem:** Simpler per-module isolation but multiplies
backup operations, requires multiple db_path settings, and complicates the test
fixture setup. Rejected.

**PostgreSQL:** Correct choice for multi-node production. For local dev and
the current single-node architecture it adds operational overhead. Migration
to Postgres is planned for Fase 9 (multi-tenancy requirement).

**Redis for kill switches (low latency reads):** Kill switch state is checked
on every consult request. SQLite reads are ~0.1ms, well within acceptable
latency. Redis adds an infrastructure dependency that is not warranted at
current scale. Rejected.

---

## Consequences

- All governance-related backups are a single `sqlite3 data/governance.db ".backup ..."` call.
- Schema changes to any governance table require a migration — use `ALTER TABLE ADD COLUMN`
  (SQLite supports this). DDL is in each manager's `_DDL` constant.
- Test fixtures create an isolated `tmp_path/gov.db` per test, with all managers initialized
  against the same path.
- In Fase 9, migration to PostgreSQL will require converting each `_DDL` constant to
  Alembic migrations and updating `aiosqlite` calls to `asyncpg`.
