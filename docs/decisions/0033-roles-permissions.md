# ADR-0033: Roles and Permission Matrix

**Status:** Accepted  
**Date:** 2026-05-12  
**Deciders:** Engineering team

---

## Context

The platform has four roles defined in `packages/admin/src/lex_agents_admin/rbac.py` (introduced in Fase 8.4). This ADR documents the canonical permission matrix for all admin and operational endpoints.

---

## Roles

| Role | Description |
|---|---|
| `analyst` | Can query the system; no admin access |
| `auditor` | Can read audit trail and governance decisions; no write |
| `operator` | Can pause/resume sources and read ops state; cannot engage kill switches or change flags |
| `admin` | Full access including kill switches, feature flags, and audit export |

Hierarchy (lowest to highest): `analyst < auditor < operator < admin`.

---

## Permission Matrix

| Endpoint | analyst | auditor | operator | admin |
|---|---|---|---|---|
| `POST /consult` | ✓ | ✓ | ✓ | ✓ |
| `GET /api/v1/admin/audit-trail` | ✗ | ✓ | ✓ | ✓ |
| `POST /api/v1/admin/audit-trail/export` | ✗ | ✗ | ✗ | ✓ |
| `GET /api/v1/admin/governance/proposals` | ✗ | ✗ | ✓ | ✓ |
| `POST /api/v1/admin/governance/proposals/*/approve` | ✗ | ✗ | ✓ | ✓ |
| `GET /api/v1/admin/governance/sources` | ✗ | ✗ | ✓ | ✓ |
| `POST /api/v1/admin/governance/sources/*/pause` | ✗ | ✗ | ✓ | ✓ |
| `GET /api/v1/admin/system/state` | ✗ | ✗ | ✓ | ✓ |
| `PUT /api/v1/admin/system/flags/*` | ✗ | ✗ | ✗ | ✓ |
| `PUT /api/v1/admin/system/kill/*` | ✗ | ✗ | ✗ | ✓ |
| `GET /api/v1/admin/agents` | ✗ | ✗ | ✗ | ✓ |
| `GET /api/v1/admin/rag/status` | ✗ | ✗ | ✗ | ✓ |
| `GET /api/v1/admin/memory/*` | ✗ | ✗ | ✗ | ✓ |
| `PUT /api/v1/admin/memory/procedural` | ✗ | ✗ | ✗ | ✓ |
| `POST /api/v1/admin/sources/*/force-resync` | ✗ | ✗ | ✗ | ✓ |

---

## Frontend enforcement

- `/admin/*` routes: redirect to `/` if role is not `operator` or `admin` (handled in `apps/web/src/app/admin/layout.tsx`).
- Write actions (kill switch button, flag toggles, force resync): buttons are rendered only for `admin` role; `operator` sees read-only views.
- The Global Kill Switch button in the admin header is rendered only when `role === "admin"`.

---

## Implementation

Role enforcement uses `require_role(*roles)` FastAPI dependency from `apps/api/src/lex_agents_api/auth.py`. Each router declares its required roles at the route level, not at the router level, to allow mixed read/write permissions on the same prefix.

---

## Consequences

- `operator` cannot engage kill switches — this is intentional to avoid accidental outages.
- `auditor` can read the full audit trail but cannot modify any system state.
- Role changes are themselves auditable events (`user.role.change` action type in audit trail).
