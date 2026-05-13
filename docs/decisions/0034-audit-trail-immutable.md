# ADR-0034: Immutable Audit Trail with Checksum Chain

**Status:** Accepted  
**Date:** 2026-04-20  
**Fase:** 8.4

---

## Context

The platform performs high-stakes governance actions (kill switches, source pauses,
prompt rollbacks) that must be traceable and tamper-evident for compliance audits.
Banking regulations require that administrative action logs cannot be retroactively
altered or deleted.

We need an audit trail that is:
1. Append-only (no UPDATE or DELETE on entries)
2. Tamper-evident (any modification is detectable)
3. Exportable for external audit review
4. Accessible to operators without database access

---

## Decision

**Implement an append-only audit trail in `governance.db` with a SHA-256 checksum chain.**

Each audit entry contains:
- `action_type`: namespaced string (`source.pause`, `kill_switch.engage`, etc.)
- `actor` + `actor_role`: who performed the action and their role at the time
- `target_type` + `target_id`: what was affected
- `reason`: mandatory free-text reason
- `correlation_id`: linked to the HTTP request that triggered the action
- `timestamp`: UTC ISO-8601
- `checksum`: `SHA-256(prev_checksum + action_type + actor + target_id + timestamp)`

**Tamper detection:** `GET /api/v1/admin/audit-trail/verify` recomputes the chain
and returns `{"valid": true/false, "entries_checked": N}`.

**Enforcement:** SQLite triggers reject any UPDATE or DELETE on the `audit_trail` table
at the database level (not only application level).

**Export:** `POST /api/v1/admin/audit-trail/export` returns JSON or CSV for a configurable
time window.

---

## Alternatives considered

**External append-only log (Kafka, S3):** More durable but requires infrastructure
complexity not justified for local/dev. Can be added as a secondary sink in Fase 9.

**Hash-only (no chain):** Individual entry hashes do not detect deletion or reordering.
The chain (each entry hashes the previous) detects both. Adopted.

**Separate database file:** Considered to isolate audit from governance. Rejected —
single `governance.db` simplifies backup, initialization, and testing (ADR-0035).

---

## Consequences

- Audit trail entries accumulate forever; no automatic pruning. For Fase 9, add an
  archival policy (e.g., move entries older than 2 years to cold storage).
- The checksum chain is only as trustworthy as the `governance.db` file itself.
  The production deployment must protect this file with OS-level permissions and
  regular backups (see runbook §8.1).
- Entries cannot be corrected — if an actor or reason was entered incorrectly, a
  new corrective entry must be added.
