"""Initial schema: lex_agents_app, lex_agents_cost, bedrock_integration.

Revision ID: 0001
Revises: —
Create Date: 2026-05-14

Migrates:
  data/governance.db   → lex_agents_app schema
  data/consultations.db → lex_agents_app.consultations
  data/cost.db          → lex_agents_cost schema

bedrock_integration schema is reserved for sub-fase 9.3 (Bedrock KB DDL is
managed by Bedrock itself; we only create the empty schema here).
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ── Create schemas ────────────────────────────────────────────────────
    op.execute("CREATE SCHEMA IF NOT EXISTS lex_agents_app")
    op.execute("CREATE SCHEMA IF NOT EXISTS lex_agents_cost")
    op.execute("CREATE SCHEMA IF NOT EXISTS bedrock_integration")

    # ── Set search_path for this session ─────────────────────────────────
    op.execute("SET search_path TO lex_agents_app")

    # ── lex_agents_app tables ─────────────────────────────────────────────

    op.execute("""
        CREATE TABLE lex_agents_app.consultations (
            id              BIGSERIAL PRIMARY KEY,
            trace_id        TEXT UNIQUE NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            query           TEXT NOT NULL,
            answer          TEXT,
            citations       JSONB,
            verification    JSONB,
            query_rewritten TEXT,
            routing         JSONB,
            metadata        JSONB,
            depth_used      TEXT,
            iterations      INTEGER,
            response_json   TEXT,
            verification_json TEXT,
            prompt_versions JSONB,
            models          JSONB,
            latency_ms      INTEGER,
            cost_estimate_usd NUMERIC(10,6)
        )
    """)
    op.execute("""
        CREATE INDEX consultations_created_at_idx
            ON lex_agents_app.consultations (created_at DESC)
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.user_feedback (
            id         BIGSERIAL PRIMARY KEY,
            trace_id   TEXT NOT NULL,
            verdict    TEXT NOT NULL CHECK (verdict IN ('aceptable', 'dudoso', 'incorrecto')),
            notes      TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.feature_flags (
            key        TEXT PRIMARY KEY,
            value      JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by TEXT NOT NULL
        )
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.kill_switches (
            target      TEXT PRIMARY KEY,
            engaged     BOOLEAN NOT NULL DEFAULT false,
            reason      TEXT,
            actor       TEXT,
            engaged_at  TIMESTAMPTZ,
            released_at TIMESTAMPTZ
        )
    """)

    # Seed mandatory kill switch targets (mirrors SQLite seed in state.py)
    op.execute("""
        INSERT INTO lex_agents_app.kill_switches (target, engaged)
        VALUES ('global', false)
        ON CONFLICT (target) DO NOTHING
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.notifications (
            id             BIGSERIAL PRIMARY KEY,
            source         TEXT NOT NULL,
            category       TEXT NOT NULL,
            title          TEXT NOT NULL,
            body           TEXT NOT NULL,
            payload        JSONB,
            correlation_id TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at        TIMESTAMPTZ,
            read_by        TEXT
        )
    """)
    op.execute("""
        CREATE INDEX notifications_created_at_idx
            ON lex_agents_app.notifications (created_at DESC)
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.prompt_evolution_proposals (
            id          BIGSERIAL PRIMARY KEY,
            pr_number   INTEGER,
            branch      TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected', 'changes_requested')),
            diff        TEXT,
            eval_report JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            decided_at  TIMESTAMPTZ,
            decided_by  TEXT
        )
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.source_status (
            source_id  TEXT PRIMARY KEY,
            status     TEXT NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'paused', 'error')),
            reason     TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by TEXT
        )
    """)

    op.execute("""
        CREATE TABLE lex_agents_app.audit_samples (
            id           BIGSERIAL PRIMARY KEY,
            trace_id     TEXT NOT NULL,
            sampled_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewer     TEXT,
            reviewed_at  TIMESTAMPTZ,
            verdict      TEXT,
            notes        TEXT
        )
    """)

    # ── audit_trail — APPEND-ONLY (ADR 0034 / ADR 0042) ──────────────────
    op.execute("""
        CREATE TABLE lex_agents_app.audit_trail (
            id            BIGSERIAL PRIMARY KEY,
            timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor_user_id TEXT NOT NULL,
            actor_role    TEXT NOT NULL,
            action_type   TEXT NOT NULL,
            target_type   TEXT NOT NULL,
            target_id     TEXT,
            before_state  TEXT,
            after_state   TEXT,
            reason        TEXT NOT NULL,
            correlation_id TEXT,
            checksum_prev TEXT,
            checksum_self TEXT
        )
    """)
    op.execute("""
        CREATE INDEX audit_trail_timestamp_idx
            ON lex_agents_app.audit_trail (timestamp DESC)
    """)

    # CRITICAL: triggers that enforce append-only semantics (mirrors SQLite triggers)
    op.execute("""
        CREATE OR REPLACE FUNCTION lex_agents_app.audit_trail_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_trail is append-only: % on row % is forbidden',
                TG_OP, OLD.id;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER audit_trail_no_update
            BEFORE UPDATE ON lex_agents_app.audit_trail
            FOR EACH ROW EXECUTE FUNCTION lex_agents_app.audit_trail_immutable()
    """)
    op.execute("""
        CREATE TRIGGER audit_trail_no_delete
            BEFORE DELETE ON lex_agents_app.audit_trail
            FOR EACH ROW EXECUTE FUNCTION lex_agents_app.audit_trail_immutable()
    """)

    # ── lex_agents_cost tables ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE lex_agents_cost.llm_usage_hourly (
            id                  BIGSERIAL PRIMARY KEY,
            hour                TIMESTAMPTZ NOT NULL,
            provider            TEXT NOT NULL CHECK (provider IN ('anthropic', 'bedrock', 'voyageai')),
            model               TEXT NOT NULL,
            input_tokens        BIGINT DEFAULT 0,
            output_tokens       BIGINT DEFAULT 0,
            cache_read_tokens   BIGINT DEFAULT 0,
            cache_write_tokens  BIGINT DEFAULT 0,
            estimated_cost_usd  NUMERIC(10,6) DEFAULT 0,
            UNIQUE (hour, provider, model)
        )
    """)

    op.execute("""
        CREATE TABLE lex_agents_cost.cost_reconciliation_daily (
            date           DATE NOT NULL,
            provider       TEXT NOT NULL,
            reported_usd   NUMERIC(10,4),
            estimated_usd  NUMERIC(10,4),
            drift_pct      NUMERIC(6,2),
            reconciled_at  TIMESTAMPTZ,
            PRIMARY KEY (date, provider)
        )
    """)

    # bedrock_integration: reserved schema, no tables yet.
    # DDL will be managed by Bedrock KB in sub-fase 9.3.
    op.execute("COMMENT ON SCHEMA bedrock_integration IS 'Reserved for Bedrock KB (sub-fase 9.3). Do not create tables manually.'")


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop in reverse order
    op.execute("DROP SCHEMA IF EXISTS bedrock_integration CASCADE")
    op.execute("DROP SCHEMA IF EXISTS lex_agents_cost CASCADE")
    op.execute("DROP SCHEMA IF EXISTS lex_agents_app CASCADE")
