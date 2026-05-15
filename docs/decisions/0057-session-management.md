# 0057 — Session Management: Cognito-compatible Adapter

**Status:** Accepted
**Date:** 2026-05-15

## Context

The platform uses stateless JWT authentication (ADR 0031). Tokens cannot be
invalidated before expiry — if a token is compromised or an admin needs to
force sign-out, there is no mechanism to do so. Cognito (planned for Fase 10.1)
would provide session management natively, but it is not yet deployed.

Requirements:

1. Admins must be able to terminate active sessions for any user.
2. Suspicious sessions (IP address shift) must be flagged in the UI.
3. The implementation must be replaceable by the Cognito API in Fase 10.1
   without changing endpoints or the admin frontend.

## Decision

Implement a session store as an **adapter** in `packages/admin/src/lex_agents_admin/sessions.py`.

### Storage

Dual-mode (same pattern as `audit_trail.py`):

- SQLite (`aiosqlite`) for local dev — table added to `governance.db`
- PostgreSQL (`asyncpg`, `lex_agents_app.sessions` table) for staging/prod

Schema:

```sql
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,           -- UUID v4
    username     TEXT NOT NULL,
    role         TEXT NOT NULL,
    ip_address   TEXT NOT NULL DEFAULT '',
    user_agent   TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,       -- now + JWT_EXPIRE_MINUTES
    revoked_at   TIMESTAMPTZ,               -- NULL = active
    revoked_by   TEXT
)
```

### JWT integration

`session_id` is embedded in the JWT claim `sid` at login:

- `issue_token_with_session()` in `auth.py` creates the session record and
  passes `session_id` to `_create_token()`.
- `require_auth()` (now `async`) reads `sid` from the token and calls
  `session_mgr.is_revoked(session_id)` — raises 401 if revoked.

### Suspicious session detection

A session is flagged `suspicious=True` if its IP `/24` prefix differs from
all of the last 3 sessions for that user. This covers IP-hopping attacks.

### Endpoints

| Method   | Path                                      | Auth              |
| -------- | ----------------------------------------- | ----------------- |
| `GET`    | `/api/v1/admin/users/{username}/sessions` | operator, admin   |
| `DELETE` | `/api/v1/admin/sessions/{session_id}`     | admin             |
| `DELETE` | `/api/v1/admin/users/{username}/sessions` | admin             |
| `GET`    | `/api/v1/me/sessions`                     | any authenticated |
| `DELETE` | `/api/v1/me/sessions/others`              | any authenticated |

### Admin UI

`/admin/users/{id}/sessions` lists active sessions in a table:

- Device type, browser (parsed from user-agent)
- IP address
- Last used / created / expires timestamps
- `Sospechosa` badge (orange) if suspicious
- "Terminar" per-row + "Terminar todas" bulk action

### Cognito migration path (Fase 10.1)

`SessionManager` is accessed via a module-level singleton (`get_session_manager()`),
identical to the `AuditTrailManager` pattern. When Cognito is deployed:

1. Create `CognitoSessionManager` implementing the same interface.
2. Call `set_session_manager(CognitoSessionManager(...))` in the lifespan.
3. No changes to endpoints, `auth.py` validation logic, or the frontend.

## Consequences

- Tokens can now be invalidated immediately (via session revocation).
- Every API request incurs one additional DB read to check revocation.
  At expected load (<1000 active users) this is negligible; a Redis cache
  can be added later if needed.
- Session records accumulate; a periodic cleanup job should purge expired
  rows (`expires_at < NOW()`) — scheduled for Fase 10.1 infrastructure.

## Alternatives considered

- **Blocklist in Redis**: Faster reads, but adds a dependency not yet in the
  stack. The DB-based approach is sufficient for MVP load.
- **Short-lived tokens (15 min) + refresh tokens**: Reduces exposure window
  without a revocation store, but requires a refresh flow in the frontend.
  Deferred to post-Cognito.
- **Cognito directly**: Not yet deployed. This adapter bridges the gap.
