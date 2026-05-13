# ADR 0042 — Persistencia y estado en AWS: migración SQLite → Aurora Serverless v2

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0007 (consultations storage), 0022 (memory), 0029 (FinOps),
0034 (audit trail), 0035 (governance DB), 0040 (RAG), 0041 (networking), 0043 (CDK)  
**Sub-fases afectadas:** 9.1 – 9.3

---

## Contexto

El estado de la aplicación está distribuido en dos SQLite locales:

- `data/governance.db`: audit_trail, feature_flags, kill_switches, notifications,
  prompt_evolution_proposals, source_status. Gestionado por `SystemStateManager`,
  `AuditTrailManager`, `NotificationManager`, `GovernanceManager`.
- `data/consultations.db`: historial de consultas jurídicas (ConsultResponse serializado).

SQLite no escala horizontalmente, no soporta múltiples writers concurrentes en ECS, y no
cumple los requisitos de backup, HA, y cifrado gestionado de DORA. Se requiere migración
a un servicio managed que mantenga la misma semántica (incluyendo audit_trail append-only).

---

## Decisión

### Aurora Serverless v2 PostgreSQL como base de datos principal

Un cluster Aurora Serverless v2 en eu-central-1 con tres schemas:

#### Schema `lex_agents_app`

Migra el contenido de `governance.db` + `consultations.db`:

```sql
-- Historial de consultas (migra consultations.db)
CREATE TABLE consultations (
    id           BIGSERIAL PRIMARY KEY,
    trace_id     TEXT UNIQUE NOT NULL,
    query        TEXT NOT NULL,
    answer       TEXT,
    citations    JSONB,
    metadata     JSONB,
    depth_used   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Feature flags (migra governance.db: feature_flags)
CREATE TABLE feature_flags (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT NOT NULL
);

-- Kill switches (migra governance.db: kill_switches)
CREATE TABLE kill_switches (
    target      TEXT PRIMARY KEY,
    engaged     BOOLEAN NOT NULL DEFAULT false,
    reason      TEXT,
    actor       TEXT,
    engaged_at  TIMESTAMPTZ,
    released_at TIMESTAMPTZ
);

-- Audit trail APPEND-ONLY (migra governance.db: audit_trail)
-- Ver sección especial más abajo.
CREATE TABLE audit_trail ( ... );

-- Notificaciones (migra governance.db: notifications)
CREATE TABLE notifications (
    id             BIGSERIAL PRIMARY KEY,
    source         TEXT NOT NULL,
    category       TEXT NOT NULL,  -- critical|warning|info
    title          TEXT NOT NULL,
    body           TEXT NOT NULL,
    payload        JSONB,
    correlation_id TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at        TIMESTAMPTZ,
    read_by        TEXT
);

-- Propuestas de evolución de prompts
CREATE TABLE prompt_evolution_proposals (
    id           BIGSERIAL PRIMARY KEY,
    pr_number    INTEGER,
    branch       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    diff         TEXT,
    eval_report  JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at   TIMESTAMPTZ,
    decided_by   TEXT
);

-- Estado de fuentes (pause/resume)
CREATE TABLE source_status (
    source_id  TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'active',
    reason     TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);

-- Audit samples para revisión humana
CREATE TABLE audit_samples (
    id           BIGSERIAL PRIMARY KEY,
    trace_id     TEXT NOT NULL,
    sampled_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewer     TEXT,
    reviewed_at  TIMESTAMPTZ,
    verdict      TEXT,
    notes        TEXT
);
```

#### Schema `lex_agents_cost`

Migra y extiende las tablas de FinOps (ADR 0029):

```sql
CREATE TABLE llm_usage_hourly (
    id           BIGSERIAL PRIMARY KEY,
    hour         TIMESTAMPTZ NOT NULL,
    provider     TEXT NOT NULL,  -- bedrock | anthropic
    model        TEXT NOT NULL,
    input_tokens BIGINT DEFAULT 0,
    output_tokens BIGINT DEFAULT 0,
    cache_read_tokens BIGINT DEFAULT 0,
    cache_write_tokens BIGINT DEFAULT 0,
    estimated_cost_usd NUMERIC(10,6) DEFAULT 0
);

CREATE TABLE cost_reconciliation_daily (
    date         DATE PRIMARY KEY,
    provider     TEXT NOT NULL,
    reported_usd NUMERIC(10,4),
    estimated_usd NUMERIC(10,4),
    drift_pct    NUMERIC(6,2),
    reconciled_at TIMESTAMPTZ
);
```

#### Schema `lex_agents_vectors`

Propiedad de Bedrock KB (pgvector). El DDL lo gestiona Bedrock KB; nosotros no modificamos
este schema directamente. Incluye la tabla `legal_chunks` descrita en ADR 0040.

### Configuración Aurora Serverless v2

| Parámetro            | Valor dev            | Valor pre            |
| -------------------- | -------------------- | -------------------- |
| Engine               | Aurora PostgreSQL 16 | Aurora PostgreSQL 16 |
| Min ACU              | 0 (auto-pause)       | 0.5                  |
| Max ACU              | 8                    | 16                   |
| Multi-AZ             | Sí (reader en 2ª AZ) | Sí                   |
| Encryption           | KMS CMK              | KMS CMK              |
| Backup retention     | 7 días PITR          | 35 días PITR         |
| Enhanced monitoring  | 60s                  | 30s                  |
| Performance Insights | Activado             | Activado             |
| Auto-pause delay     | 5 min (dev)          | —                    |

**Auto-pause en dev:** Aurora Serverless v2 pausa automáticamente tras 5 minutos sin
conexiones. Al reanudarse (~25s de cold start) las primeras requests tardan más.
Aceptable en dev; desactivado en pre/pro.

### audit_trail APPEND-ONLY en Aurora

La propiedad más crítica de `governance.db` es la inmutabilidad del audit trail (ADR 0034).
Se replica la lógica en PostgreSQL:

```sql
CREATE TABLE audit_trail (
    id           BIGSERIAL PRIMARY KEY,
    action_type  TEXT NOT NULL,
    actor        TEXT NOT NULL,
    target       TEXT,
    payload      JSONB,
    checksum     TEXT NOT NULL,  -- SHA-256 del row + checksum previo
    prev_checksum TEXT,           -- NULL para el primer registro
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trigger que rechaza UPDATE y DELETE
CREATE OR REPLACE FUNCTION audit_trail_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_trail is append-only: % on row % is forbidden',
        TG_OP, OLD.id;
END;
$$;

CREATE TRIGGER audit_trail_no_update
    BEFORE UPDATE ON audit_trail
    FOR EACH ROW EXECUTE FUNCTION audit_trail_immutable();

CREATE TRIGGER audit_trail_no_delete
    BEFORE DELETE ON audit_trail
    FOR EACH ROW EXECUTE FUNCTION audit_trail_immutable();
```

**Backup WORM adicional:**

- AWS Backup: snapshot diario de Aurora → S3 con Object Lock (Compliance mode, 7 años).
- Backup cross-region: replica a eu-west-1 automáticamente.
- PITR (Point-in-Time Recovery) activo con retención según entorno.

### S3 para documentos y artefactos

| Bucket                       | Contenido                               | Lifecycle                                 |
| ---------------------------- | --------------------------------------- | ----------------------------------------- |
| `lex-agents-raw-{env}`       | BOE XML, EUR-Lex XML crudos             | Std → IA (90d) → Glacier (365d)           |
| `lex-agents-canonical-{env}` | Canonical JSON + chunks                 | Std → IA (180d)                           |
| `lex-agents-evals-{env}`     | Eval reports, golden dataset versionado | Std siempre (activos)                     |
| `lex-agents-backups-{env}`   | Aurora snapshots exportados             | Std → Glacier (30d) → Deep Archive (365d) |

- Versioning activado en todos los buckets.
- S3 Object Lock activado en `lex-agents-backups-{env}` (WORM Governance mode, 7 años).
- Replicación S3 cross-region (eu-central-1 → eu-west-1) para DR.
- Acceso: solo via VPC Endpoint Gateway (sin acceso público).

### ElastiCache Redis: POSTPONED

En Fase 9 se empieza con caching en memoria dentro del proceso ECS (prompts cargados,
resultados de reranking frecuentes). Se añade ElastiCache Redis en Fase 10 si el profiling
muestra que la latencia de inicialización de agentes o el reranking son cuellos de botella.

Candidatos de caché para Redis futuro:

- Prompts de especialistas (1-5 KB, TTL indefinido hasta nueva versión).
- Resultados de reranking para queries idénticas (TTL 1h).
- Sesiones web JWT (TTL = JWT expiry).

### AgentCore Memory

Reemplaza `packages/memory/` SQLite local (ADR 0022):

- Memoria procedural: seeds desde `docs/knowledge/*.yaml` importados al inicializar
  AgentCore Memory store. Solo lectura en runtime.
- Memoria semántica: summaries de regulaciones, patrones de consulta. Escritura gestionada.
- Memoria episódica: **DISABLED** (ADR 0013 vigente).

---

## Migración desde SQLite

Script `scripts/migrate_sqlite_to_aurora.py` (sub-fase 9.1):

1. Leer `governance.db` con aiosqlite.
2. Conectar a Aurora via `asyncpg` (IAM auth con boto3 token).
3. Insertar todas las tablas manteniendo timestamps y checksums.
4. Verificar integridad: checksum chain del audit_trail.
5. Smoke test: N últimas entradas leídas desde Aurora vs SQLite.
6. Cutover: `DATABASE_URL` apunta a Aurora; SQLite archivado en S3.

---

## Trade-offs y consecuencias

| Trade-off                       | Impacto                                                                                                                                                  |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Aurora cold start en dev (~25s) | Aceptable. Mitigado con mínimo 0 ACU pero warm-up request al desplegar.                                                                                  |
| Shared cluster dev/pre          | Contención posible bajo carga. Mitigado: ACU escala automáticamente hasta 8/16 ACU respectivamente. Separar en Fase 10.                                  |
| Migration script uno-a-uno      | Bajo riesgo: solo dev data en Fase 9; no hay datos de clientes reales.                                                                                   |
| `asyncpg` vs `aiosqlite`        | Cambio de driver en `packages/audit/`, `packages/admin/`. Interfaz de alto nivel (`AuditTrailManager`, `SystemStateManager`) no cambia para los callers. |
| IAM auth Aurora                 | Requiere token boto3 rotado cada 15 min. Integrado en el connection pool.                                                                                |
