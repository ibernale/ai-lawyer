# 0001 — Stack técnico

**Status:** Accepted
**Date:** 2026-05-10

## Context

lex-agents requires a stack that supports: multi-agent LLM orchestration,
hybrid vector search over legal corpora (dense + sparse), a type-safe API
layer, a modern web UI, and reproducible deployments. The platform is internal
to a banking group with strict security and auditability requirements.

## Decision

### Python 3.12 + FastAPI + Pydantic v2

Python remains the dominant language for LLM tooling ecosystems. FastAPI
provides async-first HTTP with automatic OpenAPI generation and native Pydantic
v2 integration. Pydantic v2 (Rust-backed) gives strict runtime validation with
full type annotation support — critical for the citation mapping and chunk
metadata contracts where silent type coercion would compromise traceability.

`uv` replaces pip/poetry for workspace management: 10–100× faster resolution,
lock-file reproducibility, and native monorepo workspace support.

### Anthropic API (direct, no framework)

Using the Anthropic Python SDK directly rather than LangChain, LlamaIndex, or
similar frameworks. Rationale:

1. **Full control** over prompt versioning, model selection, and token budgets —
   legal accuracy requires deterministic, auditable prompt management.
2. **No framework abstraction leakage** — legal citation verification requires
   explicit control over each API call; framework "magic" creates blind spots.
3. **Cost transparency** — direct SDK exposes exact token counts per call.
4. **Model selection per agent**: `claude-opus-4-7` for legal reasoning (router +
   specialists + verifier LLM fallback), `claude-sonnet-4-6` for technical
   subagents, `claude-haiku-4-5` for Contextual Retrieval generation and
   heuristic-passed citation checks.

### Qdrant

Qdrant is selected over alternatives (Weaviate, Chroma, Pinecone) because:

1. **Native hybrid search** (dense + sparse vectors in one query, HNSW + BM42)
   without requiring a separate BM25 pipeline.
2. **Self-hosted on Docker** — data sovereignty for banking-grade PII policy.
3. **Rust performance** — low latency at the retrieval step matters for p95 SLA.
4. **Payload filtering** — jurisdiction, source, in_force_at_indexing filters
   applied natively at query time without post-processing.

See ADR 0003 for the full RAG architecture (Fase 2).

### BAAI/bge-m3 (embeddings) + BAAI/bge-reranker-v2-m3 (reranker)

bge-m3 generates both dense and sparse (SPLADE-style) vectors from a single
model pass — eliminating the need for separate dense and BM25 pipelines.
Multilingual (ES + EN + FR for EUR-Lex content). Max 8192 tokens covers full
legal articles.

bge-reranker-v2-m3 is the multilingual reranker from the same family, ensuring
embedding and reranker share the same tokenisation and semantic space.

### Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui

Server Components reduce client JavaScript bundle for an initially simple UI.
TypeScript enforces contract between API JSON and UI rendering. shadcn/ui
provides accessible components without a heavy component library lock-in.

### Docker Compose

Single-command local development (`make dev`) with Qdrant, API, and Web.
Production deployment strategy deferred to Fase 5.

## Consequences

- All agents must import from `lex-agents-shared` — no direct Anthropic client
  instantiation outside that package.
- Model IDs must not be hardcoded in business logic — loaded from prompt
  frontmatter or environment config.
- Any change to model selection requires a new ADR.

## Alternatives considered

| Alternative | Rejected because                                                           |
| ----------- | -------------------------------------------------------------------------- |
| LangChain   | Opaque abstractions; version churn; hard to audit prompt versions          |
| LlamaIndex  | Similar concerns; less control over retrieval pipeline                     |
| Weaviate    | No native hybrid search without module config complexity                   |
| Pinecone    | Managed/cloud-only; data sovereignty concern                               |
| OpenAI      | Provider lock-in; Anthropic's extended thinking better for legal reasoning |
| Poetry      | Slower than uv; workspace support less mature                              |
