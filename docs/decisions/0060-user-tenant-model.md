# ADR 0060 — User–Tenant Model (Multitenancy Identity Layer)

**Status**: Accepted  
**Date**: 2026-05-19  
**Deciders**: Engineering, Security

---

## Context

The platform already uses a `tenant_id` field on consultation and contract data,
and the JWT `tid` claim exists but always defaults to `"default"`. There is no
`tenants` table, `admin_users` has no `tenant_id` column, and there is no invitation
system. This ADR formalises the identity layer that makes multi-tenancy real.

## Decision

### Database topology

- **Shared DB, schema-per-tenant** for consultation/contract data (decided in `0002_tenant_schemas.py`).
- **Single shared identity schema** for `tenants`, `admin_users`, `sessions`,
  `tenant_invitations`, `user_audit_log`. Tenant data isolation is enforced at the
  application layer (not PostgreSQL RLS). Rationale: internal banking tool with small
  team count; RLS would add complexity without proportional benefit at this scale.

### User–tenant binding

- Every `admin_users` row has a `tenant_id` FK.
- Super-admins live in tenant `"default"` and can manage all tenants.
- Regular admins can manage users within their own tenant only.

### JWT payload

Extended to `{sub, role, tid, iat, exp, sid, jti, token_version}`:

| Claim           | Purpose                                                    |
| --------------- | ---------------------------------------------------------- |
| `sub`           | username                                                   |
| `role`          | analyst / auditor / operator / admin                       |
| `tid`           | tenant id — enforced, not defaulted                        |
| `sid`           | session id for revocation                                  |
| `jti`           | token id for high-priority per-token revocation            |
| `token_version` | monotonic counter; increment = invalidate all older tokens |

### Token revocation

Two complementary mechanisms:

1. **Session revocation** (existing): `sessions.revoked_at`; checked on every request via cache.
2. **JTI revocation** (new): `revoked_jtis` table; only for urgent cases (stolen token). Checked non-blocking; fail-open on DB error with warning log.
3. **Token version bump** (new): admin action; increments `admin_users.token_version`; any token with lower `token_version` is rejected.

### Session lifetime (Spanish banking compliance)

- JWT expiry: 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- Session TTL: 8 hours (banking work day; no overnight sessions without re-auth).
- GDPR Art.32 / PSD2 SCA compliant.

## RBAC matrix

| Role          | Own profile | Tenant users      | Invitations       | Sessions   | Tenants |
| ------------- | ----------- | ----------------- | ----------------- | ---------- | ------- |
| viewer        | read        | —                 | —                 | own        | —       |
| analyst       | read+pw     | —                 | —                 | own        | —       |
| auditor       | read        | —                 | —                 | own        | —       |
| operator      | read+pw     | —                 | —                 | own        | —       |
| admin         | read+pw     | CRUD (own tenant) | CRUD (own tenant) | own tenant | —       |
| super-admin\* | all         | all               | all               | all        | CRUD    |

\*super-admin = role `admin` in tenant `default`

## Consequences

- All existing `"default"` tenant users continue to work without change.
- New users are assigned a tenant at creation time (or via invitation).
- `FeedbackStore` must be audited to ensure `tenant_id` is enforced on queries.
- Future MFA hook point: `_create_token()` is the single place to add SCA step-up; documented in code.
