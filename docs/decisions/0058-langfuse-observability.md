# 0058 — Langfuse LLM Observability

**Status:** Accepted
**Date:** 2026-05-15

## Context

Fase 11 introduced the need to observe LLM calls in production: latency, token
usage, prompt evolution, and error rates. The infrastructure already includes a
self-hosted Langfuse v3 cluster (ADR from Fase 9.4, `LangfuseStack` in
`infra/cdk/lib/stacks/langfuse.ts`) that was deployed but never wired to the
application SDK.

Relevant constraints:
- All LLM calls go through `AnthropicClientWrapper.messages_create` in
  `packages/shared` — a single instrumentation point covers all agents.
- Langfuse must degrade gracefully: if `LANGFUSE_SECRET_KEY` is not set (local
  dev, CI), the SDK must be a no-op and must not break any call.
- API keys (public key, secret key) are sensitive and must not appear in CDK
  synthesised task definitions as plain-text environment variables.

## Decision

### SDK integration (`packages/shared`)

- Add `langfuse>=2.0` as a regular dependency of `lex-agents-shared`.
- In `anthropic_client.py`, wrap `messages_create` with a lazy-singleton
  Langfuse client (`_get_lf()`). The singleton is only initialised on first
  call, only when `LANGFUSE_SECRET_KEY` is present in the environment.
- `_lf_generation_start` opens a `trace.generation` span; `_lf_generation_end`
  closes it with model, input, output, and token usage. Both functions are
  safe no-ops on any exception so tracing never breaks the main call path.
- Langfuse SDK is added to mypy's `ignore_missing_imports` override because
  it ships without bundled stubs.

### CDK (`infra/cdk`)

- `LangfuseStack` exposes a new `langfuseApiKeysSecret` (`ISecret`) at
  `/lex-agents/{env}/langfuse/api-keys`. Operators populate it post-deploy
  with the Langfuse project public and secret keys.
- An HTTP listener (port 80) is added to the Langfuse internal ALB so the API
  container can reach it without requiring an ACM certificate in dev
  (`LANGFUSE_HOST=http://<alb-dns>`). HTTPS remains optional via context key.
- `AppServicesStack` accepts an optional `langfuseStack?: LangfuseStack` prop.
  When provided:
  - `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are injected as ECS secrets
    (fetched from Secrets Manager at task startup, never in plaintext).
  - `LANGFUSE_HOST` is added as a plain environment variable.
  - `NEXT_PUBLIC_LANGFUSE_URL` is added to the web container for the admin
    LLM-traces iframe panel.

### Settings (`apps/api`)

`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are declared
as optional `Settings` fields (empty by default) for documentation and local
`.env` overrides.

## Consequences

- Every `messages_create` call in production produces a Langfuse trace with
  model, token counts, and response content visible in the Langfuse UI.
- Local dev and CI are unaffected: the SDK check on `LANGFUSE_SECRET_KEY`
  ensures a cold start with no env var results in zero Langfuse activity.
- A new Secrets Manager secret is created per environment; its ARN is exported
  from `LangfuseStack` as a CloudFormation output.
- The Langfuse internal ALB now also listens on HTTP/80, which is acceptable
  because it is VPC-internal (not internet-facing).

## Alternatives considered

**LangSmith (AWS-hosted)**: Evaluated but rejected — self-hosted Langfuse keeps
all LLM traces within the VPC boundary, which aligns with the data-sovereignty
requirements for banking customers.

**OpenTelemetry → Langfuse bridge**: The `opentelemetry-exporter-otlp` pipeline
already exports spans to Grafana Tempo. A Langfuse OTLP ingestion endpoint is
available but requires Langfuse Enterprise. The direct SDK integration used here
covers the MVP use case with less operational complexity.

**Langfuse `@observe` decorator**: Simpler to use but requires a module-level
`Langfuse()` instance at import time, which fails loudly if keys are absent.
The lazy-singleton pattern chosen here avoids any import-time side effects.
