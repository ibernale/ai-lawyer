# Skill: User Management (Multitenancy + RBAC + Invitations)

## Overview

End-to-end user management for lex-agents. Covers tenant provisioning, user invitation,
per-tenant RBAC, session management, and token revocation. See ADR 0060 + 0061 for decisions.

## Identity layer

```
tenants
  └── admin_users (tenant_id FK)
        └── sessions
              └── revoked_jtis (high-priority per-token revocation)
tenant_invitations
user_audit_log (7-year GDPR/DORA retention)
```

## JWT payload

```json
{
  "sub": "username",
  "role": "analyst|auditor|operator|admin",
  "tid": "tenant-id",
  "iat": 1234567890,
  "exp": 1234569690,
  "sid": "session-uuid",
  "jti": "token-uuid",
  "ver": 1
}
```

## RBAC matrix

| Role | Own profile | Tenant users | Invitations | Sessions | Tenants |
|---|---|---|---|---|---|
| viewer/analyst | read | — | — | own | — |
| auditor | read | — | — | own | — |
| operator | read+pw | — | — | own | — |
| admin | read+pw | CRUD (own tenant) | CRUD (own tenant) | own tenant | — |
| super-admin* | all | all | all | all | CRUD |

*super-admin = role `admin` + `tenant_id == "default"`

## Token revocation (3 layers)

1. **Session revocation**: `sessions.revoked_at` — set via `SessionManager.revoke()`. Cached 5s.
2. **JTI revocation**: `revoked_jtis` table — for urgent per-token cases. Checked non-blocking (fail-open).
3. **Token version bump**: `admin_users.token_version++` — invalidates all tokens with lower `ver`. Use for "force re-login all devices".

## Invitation flow

```
admin → POST /api/v1/admin/invitations
      ← {id, email, role, invite_url, token}
      
user opens /auth/accept-invitation/{token}
      → POST /api/v1/auth/invitations/{token}/accept {username, password}
      ← JWT (logged in immediately)
```

Token = 32 random bytes. Stored as `HMAC-SHA256(jwt_secret, token_bytes).hexdigest()`. Single-use, 72h TTL.

## Key files

| File | Purpose |
|---|---|
| `packages/admin/src/lex_agents_admin/tenant_store.py` | Tenant CRUD |
| `packages/admin/src/lex_agents_admin/invitation_store.py` | Invitation create/accept/revoke |
| `packages/admin/src/lex_agents_admin/user_audit_store.py` | IAM audit log (7y retention) |
| `packages/admin/src/lex_agents_admin/user_store.py` | User CRUD with tenant_id + token_version |
| `packages/admin/src/lex_agents_admin/sessions.py` | Session management |
| `apps/api/src/lex_agents_api/auth.py` | JWT issuance + validation (JTI + ver checks) |
| `apps/api/src/lex_agents_api/routers/tenants.py` | Tenant API (super-admin only) |
| `apps/api/src/lex_agents_api/routers/invitations.py` | Invitation API + public accept |
| `apps/api/src/lex_agents_api/routers/ops.py` | User CRUD (updated for tenant scope) |
| `apps/web/src/components/InviteUserModal.tsx` | Invite user UI |
| `apps/web/src/app/admin/tenants/page.tsx` | Tenant list (super-admin) |
| `apps/web/src/app/auth/accept-invitation/[token]/page.tsx` | Accept invitation (public) |

## Audit log events

`user.created` | `user.disabled` | `user.enabled` | `user.role_changed`
`user.password_reset` | `user.force_relogin` |
`invitation.sent` | `invitation.accepted` | `invitation.revoked` |
`tenant.created` | `tenant.disabled` | `tenant.enabled` |
`session.revoked`

## Compliance

- **GDPR Art.5(1)(e)**: soft-delete only (`disabled=true`); no hard delete without explicit DSAR
- **GDPR Art.32**: 30-min JWT, 8h session, bcrypt passwords
- **DORA Art.9**: `user_audit_log.purge_after = now + 7 years`
- **PSD2 SCA**: 30-min token expiry. Future MFA hook point: `_create_token()` in `auth.py`
- **No PII in logs**: email only in `user_audit_log.detail` JSON, never in structlog output
