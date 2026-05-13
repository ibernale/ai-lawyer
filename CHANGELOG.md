# Changelog

All notable changes to lex-agents are documented here.
Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
