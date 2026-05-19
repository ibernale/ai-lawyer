-- Migration 0012: Create tenant_invitations table.

CREATE TABLE IF NOT EXISTS tenant_invitations (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id   TEXT NOT NULL,
    email       TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'analyst',
    token_hash  TEXT NOT NULL UNIQUE,
    invited_by  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    accepted_at TEXT,
    revoked_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_invitations_tenant ON tenant_invitations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invitations_email  ON tenant_invitations(email);
