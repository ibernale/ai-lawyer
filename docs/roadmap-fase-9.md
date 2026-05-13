# Roadmap — Fase 9: Enterprise Deployment

Target: Q3 2026. Transforms lex-agents from an internal dev platform into a
production-grade banking system deployed in Santander's infrastructure.

---

## 9.1 — SSO / Identity Federation

**Goal:** Replace username/password auth with Santander corporate identity.

- Integrate Azure AD or Okta via OIDC/OAuth 2.0 (`python-jose` → `authlib`)
- Map corporate groups to lex-agents roles (admin, operator, user)
- Remove `USER_CREDENTIALS` env variable; users managed via IdP
- Session tokens via PKCE + refresh token rotation
- MFA enforced at IdP level (no changes to lex-agents)

**Dependencies:** IT Security approval, Azure AD app registration, network policy.

---

## 9.2 — Corporate Deployment (AWS Frankfurt / On-Prem)

**Goal:** Production infrastructure with HA, DR, and data residency compliance.

- Kubernetes manifests (Helm chart) for all services
- Persistent Qdrant cluster (3-node) or managed vector DB
- PostgreSQL RDS (Frankfurt region) replacing SQLite for both `consultations.db` and `governance.db`
  - Alembic migrations from SQLite schema (ADR-0035 note)
- Persistent Jaeger with OpenSearch backend
- Secrets management via AWS Secrets Manager or Vault
- CI/CD: GitHub Actions → ECR → EKS (GitOps via ArgoCD)
- Zero-trust networking: mTLS between services

**Dependencies:** AWS account setup, DPO data residency sign-off, networking team.

---

## 9.3 — Zero Data Retention (Anthropic)

**Goal:** No consultation content stored on Anthropic servers.

- Apply for Anthropic ZDR agreement (only available to enterprise customers)
- Once active: API responses are not logged by Anthropic; TTFT may increase slightly
- Document in DPA and update privacy notice

**Dependencies:** Anthropic Enterprise contract, legal review.

---

## 9.4 — DMS Integration (SharePoint / iManage)

**Goal:** Export consultations directly to Santander's Document Management System.

- Export endpoint already exists (`/api/v1/consult/{id}/export`)
- Add DMS adapter: POST to SharePoint Online API or iManage WorkSite API
- Document metadata mapping: matter number, practice area, author
- OAuth 2.0 for DMS auth (separate from user auth)

**Dependencies:** DMS API access, legal ops team requirements.

---

## 9.5 — Commercial Legal Sources

**Goal:** Complement free sources (BOE, EUR-Lex, CENDOJ) with comprehensive databases.

Candidate sources (pending license acquisition):

| Source          | Coverage                              | Integration method     |
|-----------------|---------------------------------------|------------------------|
| Aranzadi (TR)   | ES jurisprudencia, doctrina, legislación | REST API + webhook   |
| La Ley (WK)     | ES + EU comprehensive                  | SOAP/REST API          |
| Tirant lo Blanch| ES academic + practical               | REST API               |
| EUR-Lex full    | EU full text (beyond free tier)       | SPARQL + bulk download |

Feature flag `source.aranzadi.enabled` already wired (runbook §3.6).

**Dependencies:** Commercial licenses (legal ops), API key provisioning.

---

## 9.6 — CENDOJ Production

**Goal:** Move from CENDOJ sandbox/free tier to production API with full jurisprudencia access.

- Upgrade INLABS/CENDOJ subscription to production tier
- Remove quota guard (`lex_cendoj_quota_blocked` gauge) or adjust thresholds
- Index full CENDOJ corpus (~2M sentences) — requires larger Qdrant cluster

**Dependencies:** CENDOJ production credentials, storage budget.

---

## 9.7 — Expert Validation Dataset

**Goal:** Build a gold-standard evaluation dataset validated by qualified lawyers.

- 500 question/answer pairs covering regulatory banking EU+ES
- Each answer reviewed and annotated by at least 2 qualified lawyers
- Stored in `packages/evals/data/gold_standard.jsonl`
- Integrated into CI: eval score must not regress below baseline
- Used to validate Langfuse evaluator calibration (ADR-0030)

**Dependencies:** Legal team resourcing (~40h), annotation tooling.

---

## 9.8 — Langfuse Integration

**Goal:** Activate LLM observability (ADR-0030, currently dry-run).

- Deploy Langfuse v3 self-hosted (Docker Compose → Kubernetes)
- Instrument all Anthropic API calls with Langfuse SDK
- Enable 4 alert rules in `infra/langfuse/alert_config.py`
- Connect Langfuse prompts to governance proposals (ADR-0035)
- PII redaction validation in traces before enabling

**Dependencies:** Langfuse infrastructure, DPO sign-off on trace data.

---

## 9.9 — Episodic Memory with Governance

**Goal:** Allow agents to remember prior consultations from the same user/matter.

- Extend `packages/memory` with episodic store (consultation summaries)
- Retention policy: user-controlled, default 90 days
- GDPR right-to-erasure: `DELETE /api/v1/memory/{user_id}` endpoint
- Governance: memory access requires explicit opt-in per consultation
- Audit trail entry on every memory read/write

**Dependencies:** DPO privacy assessment, legal policy.

---

## 9.10 — Drafting Agents

**Goal:** Move beyond analysis to assisted document drafting.

- New agent type: `DraftingAgent` (extends `SpecialistAgent`)
- Output: structured document with clause-level citations
- Human review gate before any draft is saved
- Scope v1: regulatory response letters, GDPR data subject responses

**Dependencies:** Expert validation dataset (9.7), legal ops workflow design.

---

## 9.11 — Multi-tenancy

**Goal:** Support multiple business units or clients within one deployment.

- Tenant isolation: separate Qdrant collections per tenant
- PostgreSQL row-level security per tenant
- Per-tenant feature flags and kill switches
- Billing attribution per tenant (extends ADR-0029)

**Dependencies:** Corporate deployment (9.2), PostgreSQL migration.

---

## 9.12 — External Notifications (Slack / Teams / Email)

**Goal:** Route critical notifications to on-call channels, not just the admin UI.

- Extend `NotificationManager` with delivery adapters: Slack webhook, MS Teams webhook, SMTP
- Routing rules: category=critical → Slack + Teams; category=warning → Slack only
- Per-user notification preferences
- Digest mode: batch warning notifications into hourly summary email

**Dependencies:** Slack/Teams workspace integration, SMTP relay.

---

## Phasing

| Sprint | Capabilities                                  |
|--------|-----------------------------------------------|
| 9.1    | SSO + corporate deployment baseline            |
| 9.2    | CENDOJ production + commercial source trial    |
| 9.3    | Langfuse + expert validation dataset           |
| 9.4    | ZDR + DMS integration                         |
| 9.5    | Episodic memory + drafting agents              |
| 9.6    | Multi-tenancy + external notifications         |
