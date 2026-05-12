# ADR-0032: Kill Switches and Feature Flags

**Status:** Accepted  
**Date:** 2026-05-12  
**Deciders:** Engineering team

---

## Context

The platform needs an operational kill switch mechanism to pause the system (globally or per-agent/source) when incidents occur, and a feature flag mechanism to gate experimental behaviours without deployments. Both require a durable audit trail.

---

## Decision

### Storage

Kill switches and feature flags are stored in `governance.db` (same SQLite file as the audit trail — ADR-0035). Two new tables:

```sql
CREATE TABLE IF NOT EXISTS feature_flags (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,   -- JSON-encoded value
    updated_at DATETIME NOT NULL,
    updated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switches (
    target TEXT PRIMARY KEY,   -- 'global' | 'agent:<name>' | 'source:<id>'
    engaged INTEGER NOT NULL DEFAULT 0,
    engaged_at DATETIME,
    engaged_by TEXT,
    reason TEXT
);
```

Seeds: `global` kill switch with `engaged=0`.

### Propagation

`SystemStateManager` (`packages/admin/src/lex_agents_admin/state.py`) is the single write path for both tables. It maintains an in-process TTL cache (5 s) so agents and endpoints can call `is_killed()` on every request without hitting SQLite every time. Kill switches invalidate the cache immediately on write.

### Enforcement

**Global kill switch** — checked in `apps/api/src/lex_agents_api/routers/consult.py` before invoking any agent:

```python
if ssm and await ssm.is_killed("global"):
    raise HTTPException(503, detail={"code": "SYSTEM_KILLED", "reason": ...})
```

`is_killed(target)` returns `True` if `global` is engaged **or** `target` itself is engaged.

**Per-agent kill switch** — checked when building agent instances (future — currently enforced via AgentStatus in the ops UI).

### Access control

All mutations (engage/release kill switch, set flag) require `admin` role. Read access to system state requires `admin` or `operator`.

### Audit trail

Every mutation emits an audit entry:
- `system.kill_switch.engage` / `system.kill_switch.release`
- `system.flag.change`

### Feature flag conventions

- Flag keys: `snake_case`, namespaced by component (e.g. `rag.reranker_enabled`, `agents.reflection_enabled`)
- Values: JSON (`true`, `false`, `42`, `"string"`)
- No flag TTL — flags persist until explicitly changed

---

## Consequences

- Single SQLite file reduces operational complexity.
- TTL cache means up to 5 s lag between flag write and enforcement (acceptable for feature flags; kill switch is immediate).
- No distributed propagation — all API replicas share the same SQLite file via filesystem mount (fine for current single-node deployment).
- Extending to distributed deployment requires replacing the TTL cache with a pub/sub mechanism (Redis, etc.) — deferred to future ADR.
