-- Migration 0011: Add tenant_id + token_version to admin_users; add JTI revocation list.
-- SQLite does not support ALTER TABLE ADD COLUMN with FK constraints directly —
-- the REFERENCES clause is ignored at DDL time but enforced by the application.

ALTER TABLE admin_users ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE admin_users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_admin_users_tenant ON admin_users(tenant_id);

-- JTI revocation list for high-priority per-token revocation
CREATE TABLE IF NOT EXISTS revoked_jtis (
    jti        TEXT PRIMARY KEY,
    revoked_at TEXT NOT NULL DEFAULT (datetime('now')),
    reason     TEXT
);
