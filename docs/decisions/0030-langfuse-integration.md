# ADR-0030: Langfuse Integration for LLM Observability

**Status:** Accepted (deferred to Fase 9)  
**Date:** 2026-04-01  
**Fase:** 8.1

---

## Context

Standard infrastructure observability (Prometheus, Jaeger) captures HTTP-level
metrics and traces but cannot introspect LLM-specific signals: token distributions,
prompt versions, evaluator scores, hallucination rates, per-trace cost attribution.

Langfuse is the leading open-source LLM observability platform. It provides:
- Trace ingestion via Python SDK or OpenAI-compatible wrapper
- Evaluator pipeline integration
- Prompt version management
- Cost attribution per model/trace
- Self-hosted deployment (important for banking data residency)

---

## Decision

**Adopt Langfuse v3 (self-hosted) as the LLM observability layer.** Integration
is deferred to Fase 9 pending:
1. Data residency review by DPO (no PII in traces — consult data is legal text, not personal data)
2. Infrastructure provisioning for Langfuse Postgres + ClickHouse in corporate environment

In the meantime:
- `infra/langfuse/alert_config.py` defines the 4 planned alert rules as a dry-run template
- The `notifications/ingest` endpoint is ready to receive Langfuse webhook alerts
- OTel traces already contain correlation IDs for future Langfuse trace linking

---

## Alert rules planned (dry-run in alert_config.py)

| Rule                    | Trigger                                    |
|-------------------------|--------------------------------------------|
| `hallucination_score_low` | Hallucination score < 0.7 on > 5 traces/h|
| `verification_red_rate`  | status=red > 10% of traces/h             |
| `trace_cost_runaway`     | Estimated cost > threshold per trace      |
| `evaluator_failure`      | Any evaluator returns error               |

---

## Alternatives considered

**Helicone:** SaaS only, data residency concern for banking. Rejected.  
**LangSmith (LangChain):** Vendor lock-in risk, not aligned with Anthropic SDK. Rejected.  
**Build in-house:** High effort for feature parity. Rejected for Fase 8; reconsider if
Langfuse does not meet requirements after Fase 9 evaluation.

---

## Consequences

- Fase 9 implementation adds ~2 weeks for Langfuse self-hosted deployment and SDK integration.
- PII redaction at the trace level must be validated before enabling (same redactor as structlog).
- Prompt version data in Langfuse will complement the governance PR proposals in ADR-0035.
