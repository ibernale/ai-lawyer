"""Tenant schema support: create_tenant_schema() helper + provision 'default' tenant.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17

Every tenant gets its own PostgreSQL schema (tenant_<id>) containing a full
copy of the application tables.  The "default" tenant reuses the existing
lex_agents_app schema for backward compatibility — no data migration needed.

To provision a new tenant at runtime call:
    SELECT create_tenant_schema('santander_es');
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# DDL that creates all application tables inside the given schema.
# Kept in sync with lex_agents_app schema from migration 0001.
_TENANT_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS {schema}.consultations (
    id                BIGSERIAL PRIMARY KEY,
    trace_id          TEXT UNIQUE NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    query             TEXT NOT NULL,
    answer            TEXT,
    citations         JSONB,
    verification      JSONB,
    query_rewritten   TEXT,
    routing           JSONB,
    metadata          JSONB,
    depth_used        TEXT,
    iterations        INTEGER,
    response_json     TEXT,
    verification_json TEXT,
    prompt_versions   JSONB,
    models            JSONB,
    latency_ms        INTEGER,
    cost_estimate_usd NUMERIC(10,6),
    branch            TEXT
);

CREATE TABLE IF NOT EXISTS {schema}.user_feedback (
    id          BIGSERIAL PRIMARY KEY,
    trace_id    TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS {schema}_consultations_created_at_idx
    ON {schema}.consultations (created_at DESC);

CREATE INDEX IF NOT EXISTS {schema}_consultations_depth_idx
    ON {schema}.consultations (depth_used);

CREATE INDEX IF NOT EXISTS {schema}_user_feedback_trace_idx
    ON {schema}.user_feedback (trace_id);
"""

_CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION create_tenant_schema(p_tenant_id TEXT)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_schema TEXT;
BEGIN
    -- Normalise: lowercase, replace non-alnum chars with underscore, prefix
    v_schema := 'tenant_' || regexp_replace(lower(p_tenant_id), '[^a-z0-9]', '_', 'g');

    -- Guard: skip if schema already exists
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = v_schema) THEN
        RAISE NOTICE 'Schema % already exists, skipping', v_schema;
        RETURN;
    END IF;

    EXECUTE format('CREATE SCHEMA %I', v_schema);

    -- consultations
    EXECUTE format('
        CREATE TABLE %I.consultations (
            id                BIGSERIAL PRIMARY KEY,
            trace_id          TEXT UNIQUE NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            query             TEXT NOT NULL,
            answer            TEXT,
            citations         JSONB,
            verification      JSONB,
            query_rewritten   TEXT,
            routing           JSONB,
            metadata          JSONB,
            depth_used        TEXT,
            iterations        INTEGER,
            response_json     TEXT,
            verification_json TEXT,
            prompt_versions   JSONB,
            models            JSONB,
            latency_ms        INTEGER,
            cost_estimate_usd NUMERIC(10,6),
            branch            TEXT
        )', v_schema);

    -- user_feedback
    EXECUTE format('
        CREATE TABLE %I.user_feedback (
            id         BIGSERIAL PRIMARY KEY,
            trace_id   TEXT NOT NULL,
            verdict    TEXT NOT NULL,
            notes      TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )', v_schema);

    -- indexes
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations (created_at DESC)',
        v_schema || '_consultations_created_at_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations (depth_used)',
        v_schema || '_consultations_depth_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.user_feedback (trace_id)',
        v_schema || '_user_feedback_trace_idx', v_schema
    );

    RAISE NOTICE 'Tenant schema % created', v_schema;
END;
$$;
"""

_DROP_FUNCTION = "DROP FUNCTION IF EXISTS create_tenant_schema(TEXT);"


def upgrade() -> None:
    # Create the helper function (idempotent via CREATE OR REPLACE)
    op.execute(_CREATE_FUNCTION)

    # lex_agents_app already has the tables (migration 0001) — no action needed
    # for the default tenant.  The function is ready to provision new tenants.


def downgrade() -> None:
    op.execute(_DROP_FUNCTION)
