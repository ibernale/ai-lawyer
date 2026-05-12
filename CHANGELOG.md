# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.3.0] — 2026-05-12

### Added

**Fase 7.3 — Comparative Law Module**

- `ComparativeResponse` schema: `JurisdictionEntry`, `ComparativeDimension`, `Divergence`, `CoverageGap` Pydantic types in `lex_agents_shared`
- `ComparativeSynthesizer`: calls claude-opus-4-7 with `sintesis_comparative/v1` prompt; auto-injects `CoverageGap` for BR/MX/UK (no-fabrication invariant)
- `output_type=analisis_comparativo`: explicit activation mode wired into standard and deep orchestrator paths
- `GET /api/v1/consult/{trace_id}/export/comparative`: 4-sheet XLSX export (pivot, divergences, risk, citations) via openpyxl
- `ComparativeView.tsx`: tabbed pivot table, divergence cards, risk badges, XLSX export link
- 4 canonical YAML eval cases (COMP-001–COMP-004) in `evals/comparative/`

**Fase 7.4 — Hardening Final**

- `CaveatBanner.tsx`: reinforced red banner on all responses; amber CENDOJ-specific variant when CENDOJ citations detected
- `FeedbackWidget.tsx` + `POST /api/v1/feedback`: user verdict (aceptable/dudoso/incorrecto) + notes stored in `user_feedback` SQLite table
- `packages/audit` (`AuditStore`, `daily_sampler`): stratified 5-samples/day by branch+depth; idempotent; `GET/PUT /api/v1/audit` REST API
- `/auditoria` frontend page: table of audit samples with modal review panel (verdict + notes)
- `unsupported_detector.py`: 4 regex categories (cuantificacion, estrategia, plazo_activo, asesoramiento_personal) return `DetectionResult` with degraded response; short-circuits before RAG in consult endpoint
- `failure_analyzer.py` extended: optional `audit_negatives` + `feedback_negatives` signals; priority scoring (audit-incorrecto: 3 pts, feedback-incorrecto: 2 pts, LeMAJ: 1 pt/case); clusters sorted by priority descending
- 9 new Prometheus metrics + Grafana panels (Document Agents, Comparative Law, Audit & Feedback, Unsupported detector)
- ADR 0028: mitigaciones por ausencia de validación experta externa
- `docs/limitations.md`: jurisdiction coverage table, unsupported patterns, development sources
- `docs/roadmap-fase-8.md`: 3 blocking prerequisites + 7 capability gates
- 30-minute demo script (`docs/demo.md`), 5 new runbook operations

### Changed

- `ConsultResponse` gains `comparative_output: ComparativeResponse | None`; backward-compatible (`answer` always populated)
- `FailedCluster` gains `priority_score`, `audit_incorrecto_count`, `feedback_incorrecto_count`
- Consult endpoint: unsupported queries return degraded response immediately (no RAG/LLM cost)

### Fixed

- `comparative_output` now propagated in `resp_with_cid` construction in consult router (was silently dropped)

---

## [0.2.0] — 2026-05-11

### Added

**PMJ — Planner/Maker/Judge pipeline**

- `LegalPlanner`: Opus tool_use decomposition of queries into multi-branch `PlannerOutput` (branches, jurisdictions, `DefinitionOfDone`)
- `CrossJurisdictionCoordinator`: runs up to 6 specialist branches in parallel; EU > national hierarchy synthesis; `⚠️ DISCREPANCIA NORMATIVA` flagging
- `LegalJudge`: Opus tool_use evaluation against DoD; ≤2 iteration circuit breaker; `is_fallback` field distinguishes genuine publish from forced fallback
- `OrchestratorV2`: depth-based routing (shallow/standard/deep); `branch_answers` per-branch visibility in `ConsultResponse`

**6 specialist branches**

- `regulatorio_bancario_ue_es` (Fase 1), `datos_personales_rgpd`, `laboral`, `mercantil_societario`, `penal_economico`, `administrativo`

**9 GREEN Dagster sources** with daily/weekly schedules

- BOE, EUR-Lex, AEPD, EDPB, BdE, EBA, ESMA, legislation.gov.uk, FCA

**LeMAJ — 5-judge evaluation panel**

- Judges: Factual, Normativa, Jurisdiccional, Completud, Cautelas + MetaJudge
- Cohen's Kappa inter-judge agreement; `review_required` flag when Kappa < 0.6
- Grafana dashboard `lemaj.json` with LDP rates, Kappa trend, nightly cost gauge

**Reflection pipeline (ADR 0021)**

- `FailureAnalyzer` → `PromptProposer` → `RegressionSim` → `PROpener`
- INVARIANT: NEVER calls `gh pr merge`; requires human review (CODEOWNERS)
- Input validation for branch names and rationale against allowlist regex

**Stratified memory (ADR 0013)**

- `ProceduralStore`: SQLite, read-only at runtime, 8 patterns across 3 jurisdictions
- `SemanticLoader`: YAML corpus, 11 jurisdictions, 16 frameworks, budget cap
- `MemoryInjector`: prepends context to LegalPlanner user_msg with `memory.injected` OTel attribute

**Adversarial testing suite (ADR 0023)**

- 6-level taxonomy × 180 YAML pairs (jailbreak, prompt injection, scope bypass, etc.)
- `has_required_caveat()` + `jailbreak_accepted()` evaluators
- CI gate: `adversarial.yml` (weekly + on push to `docs/prompts/`); zero-tolerance jailbreak threshold

**Frontend (Next.js 14)**

- Jurisdiction multi-select (11 chips: ES, EU, UK, BR, MX, US, PL, PT, AR, DE, CH)
- Branch detection banner: auto-detected vs. manual override
- Cross-jurisdiction collapsible sections (`ResponseView.tsx`) when `branch_answers` present

**API**

- `ConsultRequestBody.jurisdictions: list[str] | None` with allowlist validation (max 5)
- Prometheus metrics: `legal_query_depth_total`, `legal_query_branch_total`, `legal_query_cost_usd`

**Grafana**

- `lex-agents.json`: 5 new panels (depth distribution, branch distribution, cost per branch, LeMAJ rates, adversarial metrics)
- `lemaj.json`: new dedicated LeMAJ dashboard

**Release infrastructure**

- `.github/workflows/release.yml`: cosign keyless OIDC signing, syft SBOM, GitHub Release with CHANGELOG extraction

**Documentation**

- `docs/architecture.md`: Fase 6 full Mermaid diagram + data flow + cost model + security perimeter + known limitations
- `docs/demo.md`: expanded to 20-minute script covering all Fase 6 capabilities
- `docs/runbook.md`: 4 new operations (Dagster re-materialize, prompt evolution review, procedural pattern, new source)
- `docs/roadmap.md`: Fase 7 section (CENDOJ, episodic memory, SSO, LatAm jurisdictions, federated inference)

**ADRs**

- ADR 0019: Cross-jurisdiction coordination
- ADR 0020: LeMAJ implementation
- ADR 0021: Prompt evolution policy (no auto-merge)
- ADR 0022: Memory implementation (stratified, episodic disabled)
- ADR 0023: Adversarial testing policy

### Changed

- `LegalPlanner` accepts optional `MemoryInjector` for context injection (backwards-compatible)
- `ConsultResponse` adds `branch_answers: dict[str, str]` for per-branch visibility
- `JudgeVerdict` adds `is_fallback: bool` to distinguish genuine publish from error-forced publish
- `llm_verifier.py`: replaced deprecated `asyncio.get_event_loop()` with `asyncio.get_running_loop()`
- `CrossJurisdictionCoordinator`: explicit `n_failed` counter + `coordinator_partial_failure` log warning

### Fixed

- `pr_opener.py`: command injection via unvalidated `diff.branch` and `diff.rationale` (CRITICAL)
- `pr_opener.py`: markdown table injection via `case_id` pipe characters (CRITICAL)
- `pr_opener.py`: missing subprocess timeouts on git and gh CLI calls (CRITICAL)
- `coordinator.py`: partial branch failure silently dropped without warning or exc_info (HIGH)
- `judge.py`: fallback `publish` verdict indistinguishable from genuine publish (HIGH)

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
