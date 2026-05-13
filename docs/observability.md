# Observability — lex-agents v0.4.0

Architecture and reference for the observability stack: metrics, traces,
alerts, and dashboards.

---

## Stack overview

```
lex-agents-api
    │
    ├─ OTel SDK (Python) ──────────────────► OTel Collector (4317/4318)
    │                                              │
    │                                              ├─► Prometheus (scrape :9090)
    │                                              └─► Jaeger (OTLP gRPC :14250)
    │
    ├─ prometheus_fastapi_instrumentator ──► /metrics (scraped by Prometheus)
    │
    └─ structlog (JSON) ───────────────────► stdout → Docker log driver
```

| Component         | Port  | Purpose                              |
|-------------------|-------|--------------------------------------|
| OTel Collector    | 4317  | OTLP gRPC receiver                   |
| OTel Collector    | 4318  | OTLP HTTP receiver                   |
| Prometheus        | 9090  | Metrics storage and query            |
| Grafana           | 3001  | Dashboards and alerting              |
| Jaeger            | 16686 | Distributed trace UI                 |

---

## Metrics reference

All metrics are exposed at `GET /metrics` (Prometheus text format).

### Business metrics

| Metric                                       | Type      | Labels                     | Description                      |
|----------------------------------------------|-----------|----------------------------|----------------------------------|
| `lex_consultation_cost_usd_total`            | Counter   | `agent_id`                 | Cumulative cost per agent (USD)  |
| `lex_consultation_duration_seconds`          | Histogram | `agent_id`, `status`       | Latency by agent                 |
| `lex_verification_status_total`              | Counter   | `status` (green/red/amber) | Verification outcomes            |
| `lex_audit_samples_pending`                  | Gauge     | —                          | Unreviewed audit samples         |

### Infrastructure metrics

| Metric                                       | Type      | Labels                     | Description                      |
|----------------------------------------------|-----------|----------------------------|----------------------------------|
| `lex_cendoj_quota_blocked`                   | Gauge     | —                          | 1 when CENDOJ quota exhausted    |
| `lex_qdrant_search_duration_seconds`         | Histogram | `collection`               | Qdrant query latency             |
| `lex_source_sync_errors_total`               | Counter   | `source_id`                | Ingestion errors per source      |
| `http_request_duration_seconds`              | Histogram | `method`, `handler`, `status_code` | HTTP latency (auto)      |
| `http_requests_total`                        | Counter   | `method`, `handler`, `status_code` | HTTP request count (auto)|

---

## Grafana dashboards

Dashboards are provisioned via YAML in `infra/grafana/provisioning/dashboards/`.
Changes to the YAML files take effect on Grafana restart.

| Dashboard               | Key panels                                            |
|-------------------------|-------------------------------------------------------|
| lex-agents / Overview   | Request rate, p50/p95 latency, error rate, active sessions |
| lex-agents / Costs      | Daily cost (USD), 7-day rolling average, breakdown by agent |
| lex-agents / Sources    | Source status, ingestion errors, CENDOJ quota blocked |
| lex-agents / Audit      | Admin actions timeline, kill switch events, flag changes |

Access: `http://localhost:3001` (admin / `${GRAFANA_PASSWORD}`)

---

## Alerting

Alert rules are provisioned via `infra/grafana/provisioning/alerting/`.

### Contact points

- **local-log** — logs alert state to Grafana internal log (default for local dev)
- **api-webhook** — POSTs to `POST /api/v1/admin/notifications/ingest`, creating
  an in-app notification visible in the admin bell icon

### Tier 1 alerts (critical — immediate action required)

| Alert                  | Condition                                  | Notification        |
|------------------------|--------------------------------------------|---------------------|
| `ServiceDown`          | Docker container unhealthy > 5 min         | critical via webhook|
| `AnthropicApiErrorRate`| API error rate > 5% over 10 min           | critical via webhook|
| `QdrantUnavailable`    | Qdrant `/readyz` fails > 2 min            | critical via webhook|
| `DailyCostSpike`       | Daily cost > 2× 7-day rolling average     | critical via webhook|
| `CendojQuotaBlocked`   | `lex_cendoj_quota_blocked == 1`           | critical via webhook|

### Tier 2 alerts (warning — investigate during business hours)

| Alert                       | Condition                           | Notification         |
|-----------------------------|-------------------------------------|----------------------|
| `LlmP95LatencyHigh`         | p95 latency > threshold for 10 min  | warning via webhook  |
| `VerificationFailedRateHigh`| `status=red` > 10% over 1h         | warning via webhook  |
| `AuditSamplesPendingHigh`   | `audit_samples_pending > 30`       | warning via webhook  |
| `PromptEvolutionPRsPending` | Pending proposals > 5               | warning via webhook  |

Alert definitions: `infra/grafana/provisioning/alerting/tier1.yaml` and `tier2.yaml`.
Prometheus recording rules: `infra/prometheus/alerting_rules.yml`.

---

## Distributed tracing (Jaeger)

Every HTTP request generates a trace. Spans include:

- FastAPI route handler
- Qdrant search calls
- Anthropic API calls (wrapped in OTel span)
- Database operations (aiosqlite)

**Finding a trace:**

1. Open `http://localhost:16686`
2. Service: `lex-agents-api`
3. Filter by tag `correlation_id=<value>` (from `X-Correlation-ID` response header)

Traces are stored in Jaeger memory — they are lost on container restart.
For persistent trace storage, configure an external Jaeger backend (Fase 9).

---

## Structured logging

All application logs are JSON (structlog). Key fields:

| Field           | Description                                    |
|-----------------|------------------------------------------------|
| `event`         | Log message                                    |
| `level`         | `info`, `warning`, `error`, `critical`         |
| `timestamp`     | ISO-8601 UTC                                   |
| `correlation_id`| Propagated from `X-Correlation-ID` header      |
| `consultation_id` | Present on consult-related events            |
| `source_id`     | Present on source-related events               |

**PII redaction:** In non-dev environments (`env != "dev"`), the structured
log processor redacts patterns matching NIFs, IBANs, email addresses, and
phone numbers before writing to stdout.

Tail logs: `docker compose logs api -f`

---

## Langfuse (planned — Fase 9)

Langfuse v3 will be used for LLM-specific observability:
- Per-trace token counts and costs
- Evaluator score tracking
- Hallucination score trends
- Prompt version comparison

See ADR-0030 for the integration decision and `infra/langfuse/alert_config.py`
for the alert configuration template (dry-run until `LANGFUSE_SECRET_KEY` is set).
