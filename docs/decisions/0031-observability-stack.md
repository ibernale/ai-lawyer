# ADR-0031: Observability Stack

**Status:** Accepted  
**Date:** 2026-04-01  
**Fase:** 8.1

---

## Context

A multi-agent legal platform requires three observability pillars:
- **Metrics** — quantitative health signals (latency, error rate, cost, throughput)
- **Traces** — causal chains across agent steps for debugging
- **Logs** — human-readable event audit with structured fields

The platform runs on Docker Compose for local/dev; the corporate production target
(Fase 9) is Kubernetes on AWS Frankfurt or on-prem. The chosen stack must work
in both environments without re-instrumentation.

---

## Decision

**Adopt the OpenTelemetry standard with the following implementations:**

| Pillar   | Library                              | Storage/UI        |
|----------|--------------------------------------|-------------------|
| Metrics  | `prometheus_fastapi_instrumentator`  | Prometheus + Grafana |
| Traces   | OTel Python SDK + OTLP exporter      | OTel Collector → Jaeger |
| Logs     | structlog (JSON)                     | stdout → Docker logs / ELK (Fase 9) |

OTel Collector acts as the telemetry hub: receives OTLP from the API, fans out
to Prometheus (metrics) and Jaeger (traces). This allows swapping backends without
changing application code.

**Business metrics** (cost, verification, audit) are custom instruments defined
in `apps/api/src/lex_agents_api/metrics.py` and exposed at `/metrics`.

**Alerting** is provisioned via Grafana YAML (`infra/grafana/provisioning/alerting/`).
See ADR-0035 for how alerts route to the in-app notification center.

---

## Alternatives considered

**Datadog:** Excellent product but SaaS, per-host pricing unsuitable for banking
procurement; data residency concerns. Rejected for Fase 8.

**New Relic / Dynatrace:** Same concerns as Datadog. Rejected.

**Elastic APM:** Compatible with OTel but heavier than needed for local dev.
Will be evaluated for Fase 9 ELK integration.

**Logs only (no metrics/traces):** Insufficient for latency SLO monitoring and
cost attribution. Rejected.

---

## Consequences

- OTel auto-instrumentation adds ~10–20ms overhead on first request (cold start).
- Jaeger traces are in-memory only — lost on restart. Acceptable for dev; Fase 9
  must provision persistent Jaeger storage or migrate to Tempo.
- Prometheus data is persisted in `prometheus_data` Docker volume.
- Custom metric names use `lex_` prefix to avoid collision with default FastAPI metrics.
