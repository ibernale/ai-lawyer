# ADR 0061 — User Invitation Flow

**Status**: Accepted  
**Date**: 2026-05-19  
**Deciders**: Engineering, Security

---

## Context

There is no way to add new users to a tenant without super-admin DB access.
We need a self-service invitation flow that allows tenant admins to onboard
colleagues securely, without exposing passwords or requiring CLI access.

## Decision

### Mechanism: HMAC-SHA256 token, 72-hour TTL, single-use

```
admin → POST /api/v1/admin/invitations
      ← {invitation_id, token (plaintext, once only), invite_url}

email → user opens /auth/accept-invitation/{token}
      → sets password
      → POST /api/v1/auth/invitations/{token}/accept
      ← JWT (user is logged in immediately)
```

### Token security

- Token is 32 random bytes encoded as hex.
- Stored in DB as `HMAC-SHA256(secret_key, token_bytes).hexdigest()`.
- Never stored in plaintext; never logged.
- Token appears in plaintext exactly once: in the API response to the inviter.
- Inviter is responsible for sending the invite URL via email (or SMTP integration).

### Validation on accept

1. HMAC recomputation — reject if mismatch.
2. Expiry check — reject if `expires_at` < now.
3. Already-accepted check — reject if `accepted_at IS NOT NULL`.
4. Revoked check — reject if `revoked_at IS NOT NULL`.

### Audit trail

Every invitation action (sent, accepted, revoked) is logged to `user_audit_log`
with actor, target (email), tenant_id, and IP address.

### GDPR compliance

- Invitation email address is stored in `tenant_invitations` and `user_audit_log`.
- These are considered personal data; `user_audit_log` has `purge_after` set to
  `datetime('now', '+7 years')` for DORA retention, after which it may be purged.
- Email is never written to structlog output in plaintext.

## Alternatives considered

| Option                      | Rejected reason                                     |
| --------------------------- | --------------------------------------------------- |
| OAuth / SSO (Entra ID)      | Out of scope for MVP; planned Fase 14               |
| Magic link (no password)    | Requires email sending; password gives more control |
| Admin sets initial password | Insecure; admin knows password                      |

## Consequences

- Tenant admins can onboard users without super-admin involvement.
- Token is short-lived (72h) and single-use — limits blast radius of leaked invite.
- SMTP sending is optional for MVP (admin copies link manually).
