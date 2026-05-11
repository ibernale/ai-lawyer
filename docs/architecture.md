# lex-agents Architecture

## Table of contents

1. [System overview](#system-overview)
2. [Component map](#component-map)
3. [Full pipeline: POST /api/v1/consult](#full-pipeline)
4. [Model selection](#model-selection)
5. [Retrieval: Hybrid Search with RRF](#retrieval)
6. [Verification status policy](#verification-status)
7. [Security model](#security-model)
8. [Observability](#observability)
9. [Decision records](decisions/)

---

## System overview

lex-agents is a multi-agent legal consultation platform for internal use by banking compliance
teams. It covers Spanish and EU banking regulation (CRR, CRD IV/V, Ley 10/2014, Circular BdE, etc.).

**Non-negotiable principles:**

1. Every normative claim carries a verifiable citation. No citation → agent declares explicitly.
2. Citations are verified at claim level against indexed source chunks before returning a response.
3. All output is AI-assisted drafts requiring qualified human review.

---

## Component map

```
apps/
└── api/                       FastAPI backend
    ├── routers/
    │   ├── consult.py          POST /api/v1/consult, GET /{trace_id}, GET (list)
    │   └── rag.py              POST /api/v1/rag/search, /answer
    └── db.py                   ConsultationStore (aiosqlite + SQLite)

packages/
├── agents/                    Orchestrator-worker agents
│   └── src/lex_agents_agents/
│       ├── orchestrator.py    Lead agent — coordinates all steps with OTel spans
│       ├── router.py          Query classifier (tool_use → RoutingDecision)
│       ├── regulatorio_bancario.py  Specialist for EU+ES banking regulation
│       ├── synthesizer.py     MVP pass-through (future: multi-specialist merge)
│       ├── base_agent.py      AgentResponse, RoutingDecision, AgentMetadata types
│       └── prompt_loader.py   Versioned prompt loader with in-memory cache

├── verifier/                  Two-step citation verifier
│   └── src/lex_agents_verifier/
│       ├── pipeline.py        VerifierPipeline.run() — full orchestration
│       ├── claim_extractor.py Regex-based normative claim detection
│       ├── citation_parser.py Broken ref detection ([REF:n] not in mapping)
│       ├── heuristic_verifier.py Entity match + trigram overlap
│       └── llm_verifier.py    Haiku fallback for UNCERTAIN claims (parallel)

├── rag/                       Retrieval-augmented generation
│   └── src/lex_agents_rag/
│       ├── retriever.py       HybridRetriever — dense+sparse RRF
│       ├── reranker.py        CrossEncoderReranker / PassthroughReranker
│       ├── query_rewriter.py  Acronym expansion via Haiku
│       └── assembler.py       ContextAssembler → [REF:n] annotated context

├── ingest/                    Document ingestion pipeline
│   └── src/lex_agents_ingest/
│       ├── sources/boe.py     BOE XML scraper + parser
│       ├── sources/eurlex.py  EUR-Lex SPARQL+Cellar scraper + parser
│       ├── chunker.py         Legal-aware chunker (article/recital/sliding)
│       ├── contextualizer.py  Haiku contextual enrichment with ephemeral cache
│       ├── embedder.py        BGE-M3 dense (1024-dim) + sparse (SPLADE) embeddings
│       └── indexer.py         Qdrant upsert with named vectors

└── shared/                    Cross-package types and utilities
    └── src/lex_agents_shared/
        ├── types.py            CitationMapping, VerificationReport, ClaimVerification, …
        └── anthropic_client.py AnthropicClientWrapper with circuit breaker + retry

docs/
├── prompts/                   Versioned prompts (YAML frontmatter + markdown body)
│   ├── router/v1.md           Opus 4.7, temp=0.0, tool_use JSON schema output
│   ├── especialistas/regulatorio_bancario_ue_es/v1.md  Opus 4.7, temp=0.1, 6-section
│   ├── sintesis/v1.md         Pass-through MVP
│   └── verificador/v1.md      Haiku, temp=0.0, JSON verdict {verdict, reason}
└── decisions/                 Architecture Decision Records (ADR 0001–0008)
```

---

## Full pipeline

### POST /api/v1/consult

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant Orch as Orchestrator
    participant Router as QueryRouter
    participant RAG as HybridRetriever + Reranker
    participant Spec as RegulatorioBancario
    participant Verif as VerifierPipeline
    participant DB as SQLite

    Client->>API: POST /api/v1/consult {query}
    API->>Orch: orchestrator.run(req)

    Orch->>Router: route(query) [Opus tool_use]
    Router-->>Orch: RoutingDecision(branch, depth, jurisdictions)

    alt branch = fuera_de_alcance
        Orch-->>API: ConsultResponse (short message, no citations)
    else branch = regulatorio_bancario_ue_es
        Orch->>RAG: rewrite + dense+sparse search + rerank
        RAG-->>Orch: list[RankedChunk] → AssembledContext [REF:n]

        Orch->>Spec: run(query, assembled) [Opus]
        Spec-->>Orch: AgentResponse(answer_text, citations, metadata)

        Orch->>Verif: run(answer_text, citations, chunk_store)
        Verif->>Verif: extract claims → heuristic (entity+trigram)
        Verif->>Verif: Haiku fallback for UNCERTAIN [parallel]
        Verif-->>Orch: VerificationReport(status=green|amber|red)

        Orch-->>API: ConsultResponse
    end

    API-->>Client: ConsultResponse (immediate)
    API-->>DB: save record (BackgroundTask)
```

### OTel spans

Each step emits a named span under `orchestrator.run`:

| Span                        | Attributes                                       |
| --------------------------- | ------------------------------------------------ |
| `orchestrator.route`        | prompt.version, model, latency_ms, tokens.in/out |
| `orchestrator.rag_retrieve` | chunks_retrieved, chunks_reranked, latency_ms    |
| `orchestrator.specialist`   | specialist.name, prompt.version, model, cost_usd |
| `orchestrator.verify`       | —                                                |
| `orchestrator.synthesize`   | —                                                |

---

## Model selection

| Component               | Model                     | Rationale                                             |
| ----------------------- | ------------------------- | ----------------------------------------------------- |
| Query router            | claude-opus-4-7           | Structured tool_use, deterministic routing (temp=0.0) |
| Specialist agent        | claude-opus-4-7           | Complex multi-norm analysis requiring deep reasoning  |
| Query rewriter          | claude-haiku-4-5-20251001 | Simple acronym expansion, latency-sensitive           |
| Contextualizer (ingest) | claude-haiku-4-5-20251001 | Bulk enrichment, cost-sensitive, ephemeral caching    |
| Citation verifier (LLM) | claude-haiku-4-5-20251001 | Mechanical verdict, only for UNCERTAIN, parallelized  |

---

## Retrieval

BGE-M3 produces dense (1024-dim cosine) and sparse (SPLADE-style) vectors in one pass. Qdrant
stores them as named vectors `"dense"` and `"sparse"`.

**Reciprocal Rank Fusion:**

```
score(d) = Σ 1 / (60 + rank_i(d))   for each list i ∈ {dense, sparse}
```

Dense top-50 + sparse top-50 → RRF merge → top-30 → cross-encoder reranker → top-10 for assembly.

Each chunk is enriched at ingest time with 50–100 word contextual summary via Haiku + ephemeral
prompt caching on the parent document (reduces retrieval failure by ~67%, Anthropic 2024).

---

## Verification status

| Condition                                            | Status  | UI banner                      |
| ---------------------------------------------------- | ------- | ------------------------------ |
| Any `broken_refs` (REF:n not in mapping)             | `red`   | "Citas con errores detectados" |
| Any FAILED claim                                     | `red`   | same                           |
| Any `uncited_claims` (normative claim without REF:n) | `amber` | "Verificación parcial"         |
| Any UNCERTAIN after LLM fallback                     | `amber` | same                           |
| All PASSED, no uncited                               | `green` | "Citas verificadas"            |

---

## Security model

_Placeholder — to be completed in Fase 5 (JWT auth, RBAC, audit logging with PII redaction)._

## Observability

OTel traces exported via OTLP gRPC to `OTEL_EXPORTER_OTLP_ENDPOINT` (default: Jaeger at
`http://localhost:4317`). FastAPI auto-instrumented. Each agent span records prompt version,
model, token counts, latency, and cost estimate for per-call auditability.

See [ADR 0005](decisions/0005-observability.md).

---

## Fase 6 full stack (v0.2.0)

### System graph

```mermaid
graph TD
  User --> API[FastAPI + JWT]
  API --> OV2[OrchestratorV2]
  OV2 -->|depth=shallow| Router[QueryRouter]
  OV2 -->|standard/deep| Planner[LegalPlanner + MemoryInjector]
  Planner -->|semantic| KnowledgeYAML[docs/knowledge/]
  Planner -->|procedural| SQLite[procedural.db]
  Planner --> Coordinator[CrossJurisdictionCoordinator]
  Coordinator -->|parallel| S1[regulatorio_bancario]
  Coordinator -->|parallel| S2[datos_personales]
  Coordinator -->|parallel| S3[laboral]
  Coordinator -->|parallel| S4[mercantil]
  Coordinator -->|parallel| S5[penal_economico]
  Coordinator -->|parallel| S6[administrativo]
  S1 & S2 & S3 & S4 & S5 & S6 --> Judge[LegalJudge ≤2 iter]
  Judge --> Verifier[VerifierPipeline]
  Verifier --> API
  Dagster[Dagster Pipeline] --> Qdrant[(Qdrant)]
  Qdrant --> Retriever[HybridRetriever]
  Retriever --> Coordinator
  LeMAJ[LeMAJ 5-Judge Panel] -.->|nightly| Judge
  Reflection[Reflection Pipeline] -.->|PR opener ADR 0021| PromptStore[docs/prompts/]
  Adversarial[Adversarial Suite 180 cases] -.->|weekly CI| Metrics
```

### Data flow (standard/deep path)

1. `POST /api/v1/consult` → JWT auth → `OrchestratorV2.run()`
2. `LegalPlanner.plan()` — Opus tool_use → `PlannerOutput` (branches, jurisdictions, DoD)
3. `MemoryInjector.build_context()` — prepends semantic + procedural memory to planner user_msg
4. `HybridRetriever.search()` — dense+sparse RRF → cross-encoder rerank → `AssembledContext`
5. `CrossJurisdictionCoordinator.run_parallel()` — up to 6 specialists concurrently
6. `LegalJudge.judge()` — Opus tool_use verdict; if "revise" and iteration < 2, loops
7. `CrossJurisdictionCoordinator.synthesize()` — Opus synthesis with EU > national hierarchy
8. `VerifierPipeline.run()` — claim extraction + heuristic + Haiku fallback
9. `ConsultResponse` returned with `branch_answers`, `planner_output`, `judge_verdict`, `cost_breakdown_by_agent`

### Cost model (approximate, v0.2.0)

| Path                          | Models                                               | Typical cost |
| ----------------------------- | ---------------------------------------------------- | ------------ |
| shallow                       | Haiku (rewrite) + Opus (specialist) + Haiku (verify) | $0.05–0.15   |
| standard (2 branches)         | + Opus (planner) + Opus (synthesis)                  | $0.15–0.40   |
| deep (2 branches, 1 revision) | + Opus (judge ×2) + Opus (specialist ×4)             | $0.40–1.20   |

### Security perimeter

- JWT HS256 bearer token (8 h TTL). All `/api/v1/*` endpoints require auth.
- Input sanitization: control chars stripped, query length 10–4 000, jurisdictions allowlist.
- Prompt injection defense: claim/chunk text isolated in `<claim>` and `<chunk_text>` XML tags.
- `pr_opener.py`: branch name and rationale validated against strict allowlist regex before any git/gh call.
- No PII logged in plain text (`enable_pii_redaction=true` in prod).

### Known limitations (v0.2.0)

- Episodic memory disabled (ADR 0013: retention policy not yet approved).
- BR and MX jurisdictions have no indexed sources; planner annotates as "asesoría local requerida".
- CENDOJ integration pending CGPJ authorization (ADR 0018).
- LeMAJ and adversarial suite are nightly/weekly jobs; not in the real-time query path.
- Reflection PRs require human review before merge (ADR 0021 + CODEOWNERS); no auto-merge ever.

### PMJ model selection (Fase 6)

| Component               | Model                     | Rationale                                     |
| ----------------------- | ------------------------- | --------------------------------------------- |
| LegalPlanner            | claude-opus-4-7           | Complex decomposition requires deep reasoning |
| Specialist agents (×6)  | claude-opus-4-7           | Multi-norm jurisdiction analysis              |
| LegalJudge              | claude-opus-4-7           | Evaluative scoring against DoD                |
| Synthesis (coordinator) | claude-opus-4-7           | EU > national hierarchy merge                 |
| LeMAJ judges (×5)       | claude-opus-4-7           | Panel deliberation requires consistency       |
| Query rewriter          | claude-haiku-4-5-20251001 | Latency-sensitive, simple task                |
| Citation verifier       | claude-haiku-4-5-20251001 | Parallel mechanical verdict                   |
