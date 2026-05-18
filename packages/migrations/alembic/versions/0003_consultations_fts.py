"""Add tsvector FTS column + GIN index to consultations.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18

Adds a GENERATED ALWAYS AS ... STORED tsvector column (search_vector) to
lex_agents_app.consultations, backed by a GIN index for fast full-text search
using the 'spanish' dictionary.

The create_tenant_schema() function is replaced (CREATE OR REPLACE) so that
any tenant schema provisioned after this migration runs will also include the
FTS column and GIN index.

Existing tenant schemas (provisioned before 0003) are NOT back-filled here —
run the one-off statement from the downgrade comment if needed.
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Add FTS column + GIN index to lex_agents_app.consultations
# ---------------------------------------------------------------------------

_ADD_FTS_COLUMN = """
ALTER TABLE lex_agents_app.consultations
    ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('spanish', coalesce(query, '') || ' ' || coalesce(answer, ''))
        ) STORED;
"""

_ADD_GIN_INDEX = """
CREATE INDEX consultations_search_vector_idx
    ON lex_agents_app.consultations
    USING GIN (search_vector);
"""

# ---------------------------------------------------------------------------
# Replace create_tenant_schema() to include FTS column + GIN index
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

    -- consultations (includes search_vector generated column)
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

# ---------------------------------------------------------------------------
# Downgrade helpers
# ---------------------------------------------------------------------------

_DROP_GIN_INDEX = "DROP INDEX IF EXISTS lex_agents_app.consultations_search_vector_idx;"

_DROP_FTS_COLUMN = """
ALTER TABLE lex_agents_app.consultations DROP COLUMN IF EXISTS search_vector;
"""

# Revert create_tenant_schema() to the 0002 version (no FTS column / GIN index).
_RESTORE_FUNCTION_0002 = """
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
            branch            TEXT
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
        'CREATE INDEX %I ON %I.user_feedback (trace_id)',
        v_schema || '_user_feedback_trace_idx', v_schema
    );

    RAISE NOTICE 'Tenant schema % created', v_schema;
END;
$$;
"""


def upgrade() -> None:
    # 1. Add generated column to default-tenant table
    op.execute(_ADD_FTS_COLUMN)
    # 2. GIN index on the new column
    op.execute(_ADD_GIN_INDEX)
    # 3. Replace the provisioning function so new tenants get FTS too
    op.execute(_CREATE_FUNCTION)


def downgrade() -> None:
    # Restore the 0002 version of the provisioning function first
    op.execute(_RESTORE_FUNCTION_0002)
    # Remove index before dropping the column (PostgreSQL will cascade but
    # being explicit avoids any lock surprises)
    op.execute(_DROP_GIN_INDEX)
    op.execute(_DROP_FTS_COLUMN)
