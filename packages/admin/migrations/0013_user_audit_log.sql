-- Migration 0013: Create user_audit_log table (GDPR/DORA 7-year retention).

CREATE TABLE IF NOT EXISTS user_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT,
    ip_address  TEXT,
    detail      TEXT,
    purge_after TEXT NOT NULL DEFAULT (datetime('now', '+7 years')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_date ON user_audit_log(tenant_id, created_at);
