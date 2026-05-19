-- Migration 0010: Create tenants table
-- Run against SQLite (data/consultations.db) or PostgreSQL lex_agents_app schema.

CREATE TABLE IF NOT EXISTS tenants (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    plan       TEXT NOT NULL DEFAULT 'standard',
    disabled   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Seed the default tenant so all existing data stays valid
INSERT OR IGNORE INTO tenants (id, name, plan) VALUES ('default', 'Default Tenant', 'enterprise');
