# Changelog

All notable changes to lex-agents are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.5.0] — 2026-05-14

### Added

**Fase 9 — AWS Banking-Grade Deployment (Fases 9.1–9.5)**

**Multi-account AWS foundation (Fase 9.1, ADRs 0036–0046):**

- AWS Organizations + Control Tower: 7-account structure (management, log-archive, security,
  network, workloads-dev, workloads-pre placeholder, workloads-pro future)
- IAM Identity Center with hardware MFA mandatory; 4 permission sets (Administrator, Developer,
  DataAnalyst, SecurityAudit)
- SCPs: DenyNonEuRegions, DenyRootUsage, DenyUnencryptedStorage, DenyIAMConsolePasswordWithoutMFA
- KMS CMKs per account per purpose (rds, s3, secrets, logs, ebs) with annual auto-rotation
- CloudTrail organization trail → S3 Object Lock WORM (7-year DORA retention, eu-central-1)
- Log Archive S3 with cross-region replication (eu-west-1 DR)
- GuardDuty + Security Hub (CIS v3 + AWS FSBP standards) delegated admin in security account
- AWS Config conformance packs (CIS-AWS-3-Level1, Operational-Best-Practices-for-IAM)
- VPC 3-tier networking (public/private-app/private-data) with NAT HA × 3 AZs
- 14 VPC Interface Endpoints + S3/DynamoDB Gateway Endpoints (no internet for data plane)
- GitHub Actions OIDC trust (no long-lived AWS credentials in CI)

**Application stack on AWS (Fase 9.2, ADRs 0038–0043, 0047):**

- ECS Fargate cluster (api, web, qdrant services) behind CloudFront + ALB
- Aurora Serverless v2 PostgreSQL 16 (0–8 ACU, auto-pause 5 min dev) with IAM auth
- Dual-mode DB layer: Aurora (AWS) + SQLite (local dev), zero code change
- Bedrock as primary LLM provider with Anthropic API fallback (ADR 0039)
- Bedrock Knowledge Bases + Aurora pgvector for RAG (ADR 0040)
- Alembic migration stack (packages/migrations) with SQLite→Aurora migration scripts
- Step Functions + Lambda pipeline replacing Dagster (ADR 0047)

**Data pipelines (Fase 9.4, ADRs 0048–0051):**

- `SourcePipeline` L3 CDK construct: factory generating 1 state machine + EventBridge rule
  - CloudWatch alarm per ingest source (FetchRaw → ParseCanonical → EmbedChunks → IndexToQdrant)
- 13 sources wired: BOE, EUR-Lex, BdE, EBA, ESMA, FCA, AEPD, EDPB, CENDOJ, INLABS, SIDOF,
  TribunalConstitucional, LegislationUK
- Self-hosted Langfuse v3 on ECS Fargate + dedicated Aurora Serverless v2 (ADR 0048)
- Secrets Manager rotation: Aurora app-user 30-day auto-rotation (ADR 0050)
- S3 Cross-Region Replication with KMS re-encryption to eu-west-1 (ADR 0051)
- AWS Backup for Aurora (daily, local vault encrypted with CMK)

**Compliance & FinOps (Fase 9.5, ADRs 0044–0045, 0052):**

- **DORA evidence collection**: Lambda `evidence_collector` runs daily at 02:00 UTC, audits
  KMS rotation, CloudTrail, GuardDuty, Config compliance; publishes `ComplianceScore` metric
  to CloudWatch; stores evidence JSON + Markdown reports to Object Lock S3 bucket (7-year WORM)
- **AWS Audit Manager**: custom DORA-Banking framework with 4 control sets (Arts. 8, 9, 10, 11);
  quarterly assessment with Config/CloudTrail/Security Hub evidence sources
- **Security Hub custom insights**: Encryption coverage, MFA coverage, Network segmentation
- **ECS Fargate Spot**: API and Web services use 75% Spot weight (Qdrant remains standard —
  stateful + EFS)
- **S3 lifecycle optimized**: raw→IA@30d, Glacier@90d; canonical→IA@60d; logs→Glacier@7d
- **CloudWatch log retention**: ECS logs 30 days dev; Aurora audit logs 30 days dev
- **Cost Anomaly Detection**: dimensional monitor by SERVICE, daily alert if spend > 2×
  7-day average
- **FinOps Grafana dashboard**: cost by service, trend 30/90 days, daily vs 7-day average
- **workloads-pre account**: infrastructure provisioned (KMS, VPC, Aurora 0–4 ACU, ECR, OIDC)
  — app not deployed yet, ready for Fase 10
- **Cosign keyless image signing**: Docker images signed with Sigstore OIDC after ECR push
  (ADR 0052, DORA Art. 9.4 supply chain integrity)
- **E2E AWS test workflow** (`e2e-aws.yml`): on-demand test exercising full 14-step scenario
  (upload → parse → consult → audit trail → Langfuse → X-Ray → kill switch)

**Observability (Fase 9.3+):**

- CloudWatch X-Ray distributed tracing across ECS + Lambda + Step Functions
- Triple observability: CloudWatch + X-Ray + Langfuse
- Alert router Lambda: reads Slack webhook from Secrets Manager at runtime (not env var)
- DORA security dashboard: MTTD, login events, KMS operations, Config drift

**Documentation:**

- `docs/aws/architecture.md`: complete Mermaid multi-account architecture diagram
- `docs/aws/runbook.md`: consolidated banking-grade AWS operations runbook (16 sections)
- `docs/aws/security-controls.md`: exhaustive security controls reference
- `docs/aws/dora-mapping.md`: DORA Article mapping with evidence status
- `docs/aws/cost-model.md`: actuals vs estimates, optimization lessons
- `docs/compliance/dora-evidence-pack.md`: evidence pack structure, Athena queries,
  quarterly audit checklist
- `docs/roadmap-fase-10.md`: 10 Fase 10 initiatives with priority, dependencies, cost
- ADRs 0036–0052 all accepted

### Changed

- `apps/api/src/lex_agents_api/db.py`: dual-mode Aurora + SQLite with asyncpg connection pooling
- `packages/shared`: added `db.py` (connection management) and `secrets.py` (Secrets Manager helper)
- `apps/web/next.config.mjs`: CloudFront-aware routing, security headers
- `docs/runbook.md`: updated to v0.5.0; section 12 added pointing to `docs/aws/runbook.md`
- All `pyproject.toml` package versions bumped to 0.5.0

### Security

- No long-lived AWS credentials in CI/CD (OIDC everywhere)
- All data at rest encrypted with customer-managed KMS keys
- All transit encrypted with TLS 1.2+ (Aurora `require_secure_transport`, ALB → HTTPS)
- Secrets Manager rotation for all Aurora credentials (30-day cycle)
- Cosign keyless image signing for supply chain integrity (ADR 0052)
- CloudTrail WORM (7-year Object Lock COMPLIANCE) — DORA Art. 10.2
- GuardDuty + Security Hub CRITICAL findings → SNS → Slack within 5 minutes
- VPC Flow Logs → S3 Object Lock (log-archive account)

---

## [0.4.0] — 2026-05-13

### Added

**Admin & Governance (Fase 8)**

- **Kill switches and feature flags** (ADR-0032): `PUT /api/v1/admin/system/kill/{target}` to
  engage/release per-agent and global stop; `PUT /api/v1/admin/system/flags/{key}` for runtime
  feature gates. Global kill switch returns 503 `SYSTEM_KILLED` on all consult requests.
- **Role-based access control** (ADR-0033): `admin` role required for all mutating admin
  operations; `operator` role for read-only access. All 35 endpoint × role combinations tested.
- **Source governance**: pause/resume data sources with mandatory reason; all actions logged
  to immutable audit trail.
- **Prompt evolution governance**: `GET /api/v1/admin/governance/proposals` to review auto-generated
  prompt PRs; approve/reject/request-changes endpoints.
- **Immutable audit trail** (ADR-0034): append-only log in `governance.db` with SHA-256
  checksum chain; SQLite triggers reject UPDATE/DELETE; exportable as JSON/CSV.
- **In-app notification system** (ADR-0035): `NotificationManager` in `governance.db`; kill
  switch events create critical notifications automatically; Grafana/Dagster alerts via
  `POST /api/v1/admin/notifications/ingest` webhook; bell icon with unread badge in admin UI.
- **Notifications drawer**: slide-in panel with category filters (all/critical/warning/info),
  relative timestamps, per-item and bulk mark-read.
- **Grafana alerting provisioning**: Tier 1 (ServiceDown, AnthropicApiErrorRate, QdrantUnavailable,
  DailyCostSpike, CendojQuotaBlocked) and Tier 2 (latency, verification, audit, prompt PRs)
  alert rules; webhook contact point to notification ingest endpoint.
- **Prometheus alert rules**: `infra/prometheus/alerting_rules.yml` with recording rules for
  business metrics.
- **Langfuse alert template**: `infra/langfuse/alert_config.py` dry-run configuration for
  4 LLM-quality alert types (activated when `LANGFUSE_SECRET_KEY` is set in Fase 9).
- **Admin UI** (`/admin`): Ops Center, Governance, Audit Trail tabs; sidebar with system
  status badge; global kill switch button with reason dialog.

**Documentation**

- `docs/runbook.md`: complete rewrite with 26+ operations across 10 sections
- `docs/admin-guide.md`: UI guide with role permissions matrix
- `docs/observability.md`: full stack reference (metrics, Grafana, Jaeger, structlog, alerting)
- `docs/cost-management.md`: cost tracking, reconciliation, runaway response
- `docs/incident-response.md`: 5 structured IR procedures (P1/P2/P3/P4 severity matrix)
- `docs/demo.md`: updated to 40-minute script with Fase 8 admin section
- `docs/roadmap-fase-9.md`: detailed roadmap for enterprise deployment phase
- ADRs 0029–0031, 0034–0035: FinOps, Langfuse, observability stack, audit trail, governance DB schema

**Tests**

- `tests/e2e/test_e2e_admin_flow.py`: 21 tests across 18-step admin flow + notification ingest
- `packages/audit/tests/test_notifications.py`: 12 unit tests for `NotificationManager`

### Changed

- `apps/api/src/lex_agents_api/main.py`: `NotificationManager` initialization and SSM subscriber
  wiring; `notifications_router` included
- `apps/web/src/lib/api.ts`: `NotificationRow` type and 4 notification API functions added
- `infra/docker-compose.yml`: Grafana alerting volume mounts and provisioning paths
- `infra/prometheus.yml`: scrape config updated for alert rules

---

## [0.3.0] — 2026-04-15

### Added

**Evals & Adversarial Robustness (Fase 7.4)**

- LeMaJ LLM-as-judge evaluator framework (ADR-0014, ADR-0020)
- Automated prompt evolution pipeline with PR proposals (ADR-0015, ADR-0021)
- UnsupportedDetector: cuantificacion, estrategia, plazo_activo, asesoramiento_personal patterns
- ComparativeSynthesizer for analisis_comparativo query type
- FeedbackStore: human verdict storage for eval loop
- AuditStore: random sample capture for quality monitoring
- Adversarial robustness tests against 20+ attack patterns (ADR-0023)
- Export endpoint: `GET /api/v1/consult/{id}/export` (PDF/JSON)
- Feedback endpoint: `POST /api/v1/feedback`

---

## [0.2.0] — 2026-03-01

### Added

**Multi-jurisdiction & Orchestration (Fases 4–6.5)**

- CrossJurisdictionCoordinator: parallel specialist agent execution across EU, ES, PT, FR, DE, BR, MX
- LegalPlanner v2 with MemoryInjector and procedural memory
- OrchestratorV2 with QueryRouter (shallow/standard/deep depth)
- 6 specialist agents: regulatorio_bancario, datos_personales, laboral, mercantil, penal_economico, administrativo
- Verifier agent: per-claim citation check before response assembly
- CaveatBanner: automatic disclaimer for AI-generated legal analysis
- RAG pipeline: Qdrant + BGE-M3 embeddings, BOE + EUR-Lex sources
- OTel instrumentation, Prometheus metrics, Jaeger tracing
- CENDOJ integration (ADR-0006)

---

## [0.1.0] — 2026-01-15

### Added

- Initial FastAPI application with JWT auth, health endpoint
- Basic consultation pipeline (Planner → Specialist → Verifier)
- SQLite consultation storage
- Next.js web UI with consultation form
- Docker Compose dev stack
- CI: ruff + mypy + pytest
