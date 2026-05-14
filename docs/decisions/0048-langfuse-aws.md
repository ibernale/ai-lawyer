# ADR 0048 — Langfuse Self-Hosted on AWS (ECS + Aurora Serverless v2)

**Status:** Accepted
**Date:** 2026-05-14
**Decisores:** Ignacio Bernal (Santander)
**ADRs relacionados:** 0030 (Langfuse integration), 0036 (data residency), 0041 (networking), 0042 (persistence), 0043 (CDK)
**Sub-fase:** 9.4

---

## Context

ADR 0030 accepted Langfuse v3 (self-hosted) as the LLM observability layer and deferred
infrastructure provisioning to Fase 9. In Fase 8.1 Langfuse ran locally via Docker Compose.
Fase 9.4 migrates it to AWS while preserving all traces and prompt versions accumulated
during development.

Key constraints:
- **Data residency**: All trace data (legal text fragments, model inputs/outputs) must stay
  within EEA (eu-central-1 / eu-west-1 per ADR 0036). SaaS options rejected.
- **Banking isolation**: Langfuse must not be accessible from the public internet. Internal
  ALB only; admin access via SSM tunnel or future CloudFront with strict IP allowlist.
- **Cost**: Dev environment must minimise idle cost. Langfuse workers run infrequently;
  Aurora auto-pause acceptable.
- **ClickHouse**: Not required for MVP volumes (< 50k traces/month). Postgres backend
  is sufficient and reduces operational complexity. ADR documents upgrade path.

---

## Decision

**Deploy Langfuse v3 on ECS Fargate with a dedicated Aurora Serverless v2 cluster.**

### Why a separate Aurora cluster (not shared with DataStack)

The application Aurora cluster (DataStack) uses schema-per-concern isolation
(`lex_agents_app`, `lex_agents_cost`, `lex_agents_vectors`). Langfuse has its own
migration lifecycle, query patterns (high-volume trace inserts vs transactional app
queries), and potentially different scaling characteristics. Sharing would couple
their maintenance windows and ACU scaling events.

In dev, cost delta is minimal: Langfuse Aurora auto-pauses after 5 minutes of inactivity,
adding ~$0.06/ACU-hour only during active tracing sessions.

When trace volume justifies it (>500k traces/month), the team should evaluate sharing
the Aurora cluster (separate database, same cluster) or migrating Langfuse to
ClickHouse backend.

### Architecture

```
VPC (private subnets)
  └── LangfuseStack
        ├── Aurora Serverless v2 (PG 16)
        │     cluster: langfuse-${env}
        │     min: 0 ACU  (auto-pause 5 min in dev)
        │     max: 4 ACU  (upgrade to 8 in staging/prod)
        │     database: langfuse
        │
        ├── ECS Service: langfuse-web
        │     image: ghcr.io/langfuse/langfuse:3
        │     mode: web
        │     port: 3000
        │     tasks: 1 (dev)  →  2+ (staging/prod with ALB health check)
        │
        ├── ECS Service: langfuse-worker
        │     image: ghcr.io/langfuse/langfuse:3
        │     mode: worker
        │     tasks: 1
        │
        └── ALB (internal, port 443)
              → langfuse-web:3000
              → NOT internet-facing
              → access: SSM Session Manager port forward
                        or future CloudFront + strict IP allowlist (Fase 10)
```

### Secrets

Stored in Secrets Manager, injected as environment variables via ECS task definition:

| Secret name | Contents | Rotation |
|---|---|---|
| `/lex-agents/${env}/langfuse/database-url` | `postgresql://...` (built from Aurora credentials) | 30d (with Aurora rotation) |
| `/lex-agents/${env}/langfuse/nextauth-secret` | 32-byte random hex | Manual (90d recommended) |
| `/lex-agents/${env}/langfuse/salt` | 32-byte random hex | Manual |
| `/lex-agents/${env}/langfuse/encryption-key` | 256-bit key for credential encryption | Manual |

Note: the Langfuse secrets `/secret-key` and `/public-key` created in DataStack
(Fase 9.2) are the **API keys** used by app services to send traces — distinct from
the infrastructure secrets above.

### Migration of historical traces

Prior to cutover, export Langfuse local data via API:
```bash
# scripts/langfuse_export.py — export traces + prompts to S3
python scripts/langfuse_export.py --output s3://lex-agents-backups-dev/langfuse-export/
# After Langfuse AWS is running:
python scripts/langfuse_import.py --input s3://lex-agents-backups-dev/langfuse-export/
```

Scripts to be implemented in `packages/pipeline_aws/src/lex_pipeline_aws/langfuse_migrate/`.

---

## Consequences

### Positive
- All trace data stays within EEA; banking data residency satisfied.
- No public internet exposure; internal ALB only.
- Aurora auto-pause keeps dev cost near zero when idle.
- Langfuse v3 Postgres backend supports all required features (traces, evals, prompts).

### Negative / mitigations
- **Second Aurora cluster**: small cost overhead in dev (~$0–5/day depending on activity).
  Mitigated by auto-pause. Revisit shared cluster at Fase 10.
- **No ClickHouse**: Postgres is ~10× slower for analytics queries at scale.
  Acceptable for current volumes; documented upgrade path below.
- **SSM tunnel for admin access**: less convenient than public URL. Acceptable for
  banking environment; document tunnel procedure in `docs/aws/access.md`.

### ClickHouse upgrade path

When monthly trace volume exceeds ~500k (estimate: ~12 months post-go-live):
1. Provision ClickHouse on EC2 (or managed ClickHouse Cloud if data residency review passes).
2. Langfuse v3 supports dual-write during migration.
3. Keep Postgres for auth/metadata; route analytics to ClickHouse.

---

## Alternatives considered

| Option | Reason rejected |
|---|---|
| Langfuse Cloud (SaaS) | Data residency violation — trace data leaves EEA |
| Shared Aurora cluster (DataStack) | Coupled maintenance, different query patterns |
| Helicone | SaaS-only, data residency concern |
| Build in-house LLM observability | High effort; rejected in ADR 0030 |
