"""Add contracts table for Fase 13A contract analysis.

Revision ID: 0005
Revises: 0003
Create Date: 2026-05-18

Creates lex_agents_app.contracts and updates create_tenant_schema() to include
the contracts table for new tenants provisioned after this migration.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0003"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Create contracts table in the default-tenant schema
# ---------------------------------------------------------------------------

_CREATE_CONTRACTS_TABLE = """
CREATE TABLE lex_agents_app.contracts (
    id                   BIGSERIAL PRIMARY KEY,
    contract_id          TEXT UNIQUE NOT NULL,
    trace_id             TEXT UNIQUE NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    filename             TEXT NOT NULL,
    document_type        TEXT,
    parties              JSONB,
    jurisdiction         JSONB,
    governing_law        TEXT,
    applicable_framework JSONB,
    overall_risk_score   NUMERIC(4,3),
    overall_risk_rating  TEXT,
    analysis_json        JSONB,
    status               TEXT NOT NULL DEFAULT 'pending',
    latency_ms           INTEGER,
    cost_estimate_usd    NUMERIC(10,6),
    error_message        TEXT
);
"""

_CREATE_CONTRACTS_CREATED_AT_IDX = """
CREATE INDEX contracts_created_at_idx
    ON lex_agents_app.contracts (created_at DESC);
"""

_CREATE_CONTRACTS_STATUS_IDX = """
CREATE INDEX contracts_status_idx
    ON lex_agents_app.contracts (status);
"""

_CREATE_CONTRACTS_DOCUMENT_TYPE_IDX = """
CREATE INDEX contracts_document_type_idx
    ON lex_agents_app.contracts (document_type);
"""

# ---------------------------------------------------------------------------
# Replace create_tenant_schema() to include contracts table (full body)
# ---------------------------------------------------------------------------

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

    -- consultations (includes search_vector generated column from 0003)
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
            branch            TEXT,
            search_vector     tsvector
                GENERATED ALWAYS AS (
                    to_tsvector(''spanish'',
                        coalesce(query, '''') || '' '' || coalesce(answer, ''''))
                ) STORED
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

    -- contracts (Fase 13A)
    EXECUTE format('
        CREATE TABLE %I.contracts (
            id                   BIGSERIAL PRIMARY KEY,
            contract_id          TEXT UNIQUE NOT NULL,
            trace_id             TEXT UNIQUE NOT NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            filename             TEXT NOT NULL,
            document_type        TEXT,
            parties              JSONB,
            jurisdiction         JSONB,
            governing_law        TEXT,
            applicable_framework JSONB,
            overall_risk_score   NUMERIC(4,3),
            overall_risk_rating  TEXT,
            analysis_json        JSONB,
            status               TEXT NOT NULL DEFAULT ''pending'',
            latency_ms           INTEGER,
            cost_estimate_usd    NUMERIC(10,6),
            error_message        TEXT
        )', v_schema);

    -- consultations indexes
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations (created_at DESC)',
        v_schema || '_consultations_created_at_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations (depth_used)',
        v_schema || '_consultations_depth_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations USING GIN (search_vector)',
        v_schema || '_consultations_search_vector_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.user_feedback (trace_id)',
        v_schema || '_user_feedback_trace_idx', v_schema
    );

    -- contracts indexes
    EXECUTE format(
        'CREATE INDEX %I ON %I.contracts (created_at DESC)',
        v_schema || '_contracts_created_at_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.contracts (status)',
        v_schema || '_contracts_status_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.contracts (document_type)',
        v_schema || '_contracts_document_type_idx', v_schema
    );

    RAISE NOTICE 'Tenant schema % created', v_schema;
END;
$$;
"""

# ---------------------------------------------------------------------------
# Downgrade helpers
# ---------------------------------------------------------------------------

_DROP_CONTRACTS_INDEXES = """
DROP INDEX IF EXISTS lex_agents_app.contracts_document_type_idx;
DROP INDEX IF EXISTS lex_agents_app.contracts_status_idx;
DROP INDEX IF EXISTS lex_agents_app.contracts_created_at_idx;
"""

_DROP_CONTRACTS_TABLE = """
DROP TABLE IF EXISTS lex_agents_app.contracts;
"""

# Revert create_tenant_schema() to the 0003 version (without contracts table).
_RESTORE_FUNCTION_0003 = """
CREATE OR REPLACE FUNCTION create_tenant_schema(p_tenant_id TEXT)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_schema TEXT;
BEGIN
    v_schema := 'tenant_' || regexp_replace(lower(p_tenant_id), '[^a-z0-9]', '_', 'g');

    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = v_schema) THEN
        RAISE NOTICE 'Schema % already exists, skipping', v_schema;
        RETURN;
    END IF;

    EXECUTE format('CREATE SCHEMA %I', v_schema);

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
            branch            TEXT,
            search_vector     tsvector
                GENERATED ALWAYS AS (
                    to_tsvector(''spanish'',
                        coalesce(query, '''') || '' '' || coalesce(answer, ''''))
                ) STORED
        )', v_schema);

    EXECUTE format('
        CREATE TABLE %I.user_feedback (
            id         BIGSERIAL PRIMARY KEY,
            trace_id   TEXT NOT NULL,
            verdict    TEXT NOT NULL,
            notes      TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )', v_schema);

    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations (created_at DESC)',
        v_schema || '_consultations_created_at_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations (depth_used)',
        v_schema || '_consultations_depth_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.consultations USING GIN (search_vector)',
        v_schema || '_consultations_search_vector_idx', v_schema
    );
    EXECUTE format(
        'CREATE INDEX %I ON %I.user_feedback (trace_id)',
        v_schema || '_user_feedback_trace_idx', v_schema
    );

    RAISE NOTICE 'Tenant schema % created', v_schema;
END;
$$;
"""


def upgrade() -> None:
    # 1. Create contracts table in default-tenant schema
    op.execute(_CREATE_CONTRACTS_TABLE)
    # 2. Indexes on contracts
    op.execute(_CREATE_CONTRACTS_CREATED_AT_IDX)
    op.execute(_CREATE_CONTRACTS_STATUS_IDX)
    op.execute(_CREATE_CONTRACTS_DOCUMENT_TYPE_IDX)
    # 3. Replace the provisioning function so new tenants get contracts too
    op.execute(_CREATE_FUNCTION)


def downgrade() -> None:
    # 1. Restore the 0003 version of the provisioning function
    op.execute(_RESTORE_FUNCTION_0003)
    # 2. Drop contracts indexes (explicit before table drop)
    op.execute(_DROP_CONTRACTS_INDEXES)
    # 3. Drop the contracts table
    op.execute(_DROP_CONTRACTS_TABLE)
