# 0005 — Estrategia de observabilidad

**Status:** Accepted
**Date:** 2026-05-10

## Context

lex-agents makes LLM API calls that are expensive, variable-latency, and
non-deterministic. For a legal platform, being able to trace exactly which
prompt version was used, what tokens were consumed, and whether the verifier
passed or rejected a claim is critical for debugging, auditing, and cost control.

The observability stack must work locally without external SaaS (banking
context, data sensitivity), be lightweight enough to run in Docker Compose,
and be extensible to a full production-grade stack in Fase 5.

## Decision

### structlog for structured logging

Python's stdlib `logging` module uses string formatting that is hostile to
machine parsing. `structlog` emits JSON events with typed key-value pairs,
making log aggregation and querying (e.g. in Grafana Loki or Elasticsearch)
straightforward without log parsing pipelines.

Key processors configured:

- `TimeStamper(fmt="iso")` — ISO 8601 timestamps
- `merge_contextvars` — binds correlation_id from the request context
- `_pii_redactor` — redacts PII fields before any log sink (see ADR 0001,
  skill `security-and-pii`)
- `JSONRenderer` — output as machine-parseable JSON

### OpenTelemetry SDK for distributed tracing

OTel is the industry standard; it avoids vendor lock-in and works with Jaeger,
Zipkin, Grafana Tempo, and Datadog without code changes (only exporter swap).
Traces are exported via OTLP gRPC to the otel-collector sidecar.

Every Anthropic API call will be wrapped in a span with attributes:

- `llm.model`, `llm.prompt_version`, `llm.input_tokens`, `llm.output_tokens`,
  `llm.latency_ms`

This gives per-call cost and latency visibility from day one.

### Jaeger for local trace visualisation

Jaeger `all-in-one` is the simplest way to view distributed traces locally
without configuration overhead. UI available at `http://localhost:16686`.
It is never exposed publicly.

### otel-collector as trace aggregation layer

A dedicated collector decouples the application from the backend. In Fase 5,
changing from Jaeger to Grafana Tempo is a one-line change in
`infra/otel-collector-config.yaml`, zero application code changes.

### Fase 5 plan: metrics + alerting

In Fase 5 the observability stack will be extended with:

- **Prometheus**: scrape metrics from FastAPI (via `prometheus-fastapi-instrumentator`)
  and Qdrant (native `/metrics` endpoint)
- **Grafana**: dashboards in `infra/grafana/dashboards/` as provisioned JSON
- **Alertmanager**: alert on `legal_quality_score` regression, high
  `hallucination_rate`, and circuit breaker open events
- **Grafana Loki**: structured log aggregation (structlog → Promtail → Loki)

## Consequences

- All log output is JSON — no plain text log lines in production.
- PII redaction is applied before any log sink; developers do not see raw
  user queries in logs (only in DEBUG mode in dev with `ENV=dev`).
- Trace data stays local (Jaeger); no user data leaves the infrastructure.
- Adding a new agent call requires wrapping it in an OTel span — this is
  enforced via the `legal-code-reviewer` subagent checklist.

## Alternatives considered

| Alternative      | Rejected because                                                  |
| ---------------- | ----------------------------------------------------------------- |
| stdlib `logging` | String-formatted; not machine-parseable without regex parsing     |
| Datadog APM      | SaaS; data sovereignty concern for banking context                |
| Zipkin           | Less ecosystem support than Jaeger; no Grafana native integration |
| OpenCensus       | Deprecated in favour of OTel                                      |
| Sentry           | Good for errors, not for LLM call tracing and token cost tracking |
