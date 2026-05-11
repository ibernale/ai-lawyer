# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.1.0] — 2026-05-11

First production-candidate release. MVP covering EU+ES banking regulation.

### Added

**Security (Fase 5)**
- JWT authentication with `python-jose` + `passlib[bcrypt]`; users defined in `AUTH_USERS_JSON` env var
- Rate limiting via `slowapi`: 30 req/min on `/api/v1/consult`, 120 req/min on other routes
- `ContentSizeMiddleware`: rejects requests > 64 KB with HTTP 413
- `SecurityHeadersMiddleware`: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
- Input sanitization: Pydantic `Field(min_length=10, max_length=4000)` + control-char strip on query
- Security CI workflow: pip-audit, npm audit, trufflehog secrets scan
- Auth router `POST /auth/token` (public; form-based credentials)

**Observability**
- Prometheus metrics at `/metrics` via `prometheus-fastapi-instrumentator`
- Grafana dashboard (5 panels: RPS, latency p50/p95, error rate, cost) in docker-compose
- `make grafana` target to open dashboard

**Frontend**
- Permanent sticky disclaimer banner on `/consulta` — not dismissable
- Collapsible metadata panel in `ResponseView`: model, prompt_version, latency_ms, cost, query_rewritten
- Export Word button (`GET /{trace_id}/export`) → `.docx` with cover, analysis, citations, verification, disclaimer
- Report problem button (`POST /{trace_id}/feedback`) → `FeedbackModal` with issue_type + description
- `/legal` page listing and linking privacy, AI disclosure, third parties, limitations docs

**DOCX export (Fase 5)**
- `GET /api/v1/consult/{trace_id}/export` — generates `.docx` with `python-docx`
- Includes legal disclaimer banner in cover and footer

**Feedback loop**
- `POST /api/v1/consult/{trace_id}/feedback` — saves JSON to `evals/feedback/`

**Legal documentation**
- `docs/legal/privacy.md` — data processing, retention, Anthropic as sub-processor, ZDR
- `docs/legal/ai_disclosure.md` — what the system does/doesn't do, user obligations
- `docs/legal/third_parties.md` — Anthropic, Qdrant, HuggingFace, Jaeger, GitHub
- `docs/legal/limitations.md` — hallucinations, coverage gaps, unvalidated dataset

**Docs**
- `docs/runbook.md` — complete: startup, ingestion, Qdrant ops, key rotation, troubleshooting, observability, on-call
- `docs/demo.md` — 10-min demo guion with 3 queries (easy/medium/out-of-scope)
- `docs/roadmap.md` — prioritized: CENDOJ, PT/BR/MX, mercantil, fine-tuned reranker, SSO
- `docs/reports/2026-05-11-mvp-v0.1.0.md` — pre-release eval baseline

**Evaluation framework (Fase 4)**
- 25 banking cases (`BANK-EU-001` to `025`) + 5 negative (`NEG-001` to `005`) + 5 smoke
- Runner CLI: `python -m evals run` / `python -m evals compare`
- 10-metric scoring: citation_recall, citation_precision, hallucination_rate, concept_coverage, forbidden_claim_rate, caveat_coverage, legal_quality_score, latency p50/p95, cost
- CI workflows: smoke (push to main) + full (nightly) with hard thresholds
- `make eval` / `make eval-quick` / `make test-cov` targets

### Fixed

- **Critical:** Verifier was never instantiated — `verifier=None` was hardcoded in `_get_orchestrator()`. Fixed by wiring `VerifierPipeline` to `OrchestratorDeps`.
- **Security:** Prompt injection in `LLMVerifier._call_haiku` — adversarial content in Qdrant chunks could override system prompt. Fixed by separating system/user message with XML tags.

### Changed

- All `/api/v1/*` endpoints now require JWT Bearer auth (`require_auth` dependency)
- `ConsultRequestBody.query` enforces `min_length=10`, `max_length=4000`, strips control characters
- `main.py` app factory registers auth, rate limiter, Prometheus, and all routers
- `ResponseView.tsx` substantially extended with citation chips, verification banner, metadata panel, export/feedback actions

---

## [0.0.4] — 2026-04-xx

Eval framework (Fase 4). See commit `4bf15f6`.

## [0.0.3] — 2026-03-xx

Agents, verifier, /consult endpoint, frontend (Fase 3). See commit `0a15a4c`.

## [0.0.2] — 2026-02-xx

RAG pipeline — ingest BOE/EUR-Lex, hybrid search (Fase 2). See commit `6662569`.

## [0.0.1] — 2026-01-xx

Infrastructure, CI/CD, backend base, frontend base (Fase 1). See commit `4437606`.

## [0.0.0] — 2026-01-xx

Repository bootstrap (Fase 0). See commit `6fda95f`.
