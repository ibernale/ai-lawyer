# 0059 — Jaeger Distributed Tracing on AWS

**Status:** Accepted
**Date:** 2026-05-15

## Context

The API already exports OTLP traces via `opentelemetry-exporter-otlp-proto-grpc`
to an OTEL Collector in docker-compose local dev (`otel-collector:4317`). In
production (ECS Fargate), there was no trace backend — the exporter endpoint
defaulted to `localhost:4317` which goes nowhere.

The admin panel already has a "Traces Infra" page (`/admin/platform/traces-infra`)
that embeds Jaeger UI via `NEXT_PUBLIC_JAEGER_URL`. Completing the wiring requires
a self-hosted Jaeger deployment on AWS and the correct OTLP endpoint injected into
the API container.

Constraints:

- The existing OTEL Collector in docker-compose already accepts both gRPC (4317)
  and HTTP (4318) — both protocols are supported locally.
- AWS ALB can proxy HTTP but not raw TCP/gRPC on arbitrary ports without
  significant additional complexity (gRPC over ALB requires HTTP/2 + TLS).
- Traces are non-critical: loss on container restart is acceptable for dev/MVP.

## Decision

### Transport: switch to OTLP HTTP (port 4318)

Replace `opentelemetry-exporter-otlp-proto-grpc` with
`opentelemetry-exporter-otlp-proto-http` in `apps/api`. The HTTP exporter:

- Sends traces to `POST /v1/traces` over plain HTTP — fully ALB-compatible.
- Works identically with the existing docker-compose OTEL Collector (which
  already listens on port 4318).
- Removes the gRPC dependency and the `insecure=True` workaround.

Default `OTEL_EXPORTER_OTLP_ENDPOINT` updated to `http://localhost:4318`.

### Infrastructure: `JaegerStack` CDK stack

A new `JaegerStack` (`infra/cdk/lib/stacks/jaeger.ts`) deploys:

- ECS Fargate with `jaegertracing/all-in-one:1.76.0`, 512 CPU / 1024 MB.
- In-memory trace storage (`SPAN_STORAGE_TYPE=memory`, max 50 000 traces).
- Internal ALB (VPC-only) with two listeners:
  - Port 80 → Jaeger UI (container port 16686) — `NEXT_PUBLIC_JAEGER_URL`
  - Port 4318 → OTLP HTTP (container port 4318) — `OTEL_EXPORTER_OTLP_ENDPOINT`
- Outputs: `JaegerUiUrl`, `JaegerOtlpUrl`.

`AppServicesStack` accepts an optional `jaegerStack?: JaegerStack` prop.
When provided:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://<alb-dns>:4318` is injected into the API
  container environment.
- `NEXT_PUBLIC_JAEGER_URL=http://<alb-dns>` is injected into the web container.

`app.ts` instantiates `JaegerStack` before `AppServicesStack` and passes it as
a prop.

## Consequences

- Every FastAPI request in production produces an OTEL span visible in the
  Jaeger UI embedded in the admin panel.
- docker-compose local dev continues to work unchanged (OTEL Collector accepts
  HTTP on 4318).
- Traces are ephemeral: on Jaeger task restart (deploy, OOM), all traces are
  lost. This is acceptable for Fase 11 MVP. Persistent storage (Cassandra or
  OpenSearch) is a Fase 12 upgrade path.
- The `otel-collector-config.yaml` retains the gRPC receiver (4317) for
  backwards-compatibility with any local tooling that still targets port 4317.
- The `JaegerStack` adds one ECS task and one internal ALB to the AWS bill.

## Alternatives considered

**AWS X-Ray**: Native to AWS, no extra infrastructure. Rejected because X-Ray UI
is not embeddable in an iframe and the existing Jaeger admin panel page would
need a full redesign.

**OTLP gRPC + NLB**: Keep the gRPC exporter and use a Network Load Balancer for
TCP 4317. Rejected: NLBs are more expensive and harder to secure than ALBs; the
HTTP exporter is functionally equivalent.

**Sidecar OTEL Collector in ECS**: Add a collector sidecar to the API task
definition. Rejected for MVP: it adds operational complexity (config updates
require redeployment). Can be added later for richer pipeline processing
(sampling, tail-based filtering).

**Grafana Tempo**: The ObservabilityStack could be extended with Tempo. Deferred
to a future phase when Grafana dashboards correlating metrics + traces are needed.
