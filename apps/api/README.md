# apps/api

FastAPI backend for the lex-agents platform. Exposes REST endpoints for legal
consultation queries, ingestion triggers, and evaluation runs. Delegates
reasoning to `packages/agents`, retrieval to `packages/rag`, and citation
verification to `packages/verifier`. Emits structured JSON logs via `structlog`
with configurable PII redaction.
