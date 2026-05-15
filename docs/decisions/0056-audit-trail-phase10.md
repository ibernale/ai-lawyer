# 0056 — Audit Trail Extension: Fase 10 Action Types

**Status:** Accepted
**Date:** 2026-05-15

## Context

The audit trail `ACTION_TYPES` frozenset (ADR 0035) contained 18 types covering
system, governance, and federation events, but was missing user lifecycle, session,
and observability-access events introduced in Fase 10.

Specifically absent:

- Authentication events (`user.login.success`, `user.login.fail`, `user.logout`)
- User administration (`user.invite.*`, `user.disable`, `user.delete`, etc.)
- Session management (`session.terminate`, `session.terminate_all`)
- Embedded tool access (`grafana.embedded_access`, etc.)

## Decision

Add 19 new action types to `ACTION_TYPES` in
`packages/audit/src/lex_agents_audit/audit_trail.py`:

### User lifecycle

| Type                        | Trigger                                            |
| --------------------------- | -------------------------------------------------- |
| `user.invite.send`          | Admin sends invitation email                       |
| `user.invite.expire`        | Invitation link expires                            |
| `user.activate`             | User activates account via invite link             |
| `user.login.success`        | Successful login (logged with IP + user-agent)     |
| `user.login.fail`           | Failed login attempt (logged with IP + user-agent) |
| `user.logout`               | Explicit logout                                    |
| `user.password.change`      | Password updated                                   |
| `user.mfa.enable`           | MFA activated                                      |
| `user.mfa.disable`          | MFA deactivated                                    |
| `user.disable`              | Account disabled by admin                          |
| `user.enable`               | Account re-enabled                                 |
| `user.delete`               | Account deleted                                    |
| `user.force_password_reset` | Admin forces password reset                        |

(Note: `user.role.change` was already present in the original set.)

### Session

| Type                    | Trigger                                  |
| ----------------------- | ---------------------------------------- |
| `session.terminate`     | Admin terminates a single session        |
| `session.terminate_all` | Admin terminates all sessions for a user |

### Embedded observability access

| Type                       | Trigger                    |
| -------------------------- | -------------------------- |
| `grafana.embedded_access`  | User views Grafana iframe  |
| `langfuse.embedded_access` | User views Langfuse iframe |
| `jaeger.embedded_access`   | User views Jaeger iframe   |

### Login event logging

`user.login.success` and `user.login.fail` are logged from
`apps/api/src/lex_agents_api/routers/auth.py` on every `POST /auth/token` call,
with `after={"ip": "<client_ip>", "user_agent": "<ua>"}` for forensic purposes.

PII note: IP address and user-agent are considered operational metadata in a
banking platform context and are logged consistently with existing server logs.

## Consequences

- The audit trail now covers the full user authentication lifecycle.
- Security reviews can query `user.login.fail` events grouped by IP or
  username to detect brute-force or credential-stuffing patterns.
- Session revocation events (`session.terminate*`) provide accountability
  for forced sign-outs by admins.
- `grafana/langfuse/jaeger.embedded_access` events are not yet wired to the
  federation router — they are reserved for Fase 10.1 when the iframe proxy is
  deployed.

## Alternatives considered

- **Open-ended action types (string)**: Rejected — the closed frozenset
  constraint (ADR 0035) ensures all action types are reviewed and documented.
