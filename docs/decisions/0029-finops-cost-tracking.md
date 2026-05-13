# ADR-0029: FinOps — Cost Tracking Strategy

**Status:** Accepted  
**Date:** 2026-04-01  
**Fase:** 8.1

---

## Context

The platform calls the Anthropic API on every consultation. In an internal
banking context, understanding and controlling AI spend is a compliance and
operational requirement. We need cost visibility at three levels: per-consultation,
per-agent, and aggregate daily/weekly.

Anthropic does not provide real-time per-call billing in the standard API
response; cost must be estimated from token counts and published pricing.

---

## Decision

**Estimate cost from token counts at call time** and publish as Prometheus counters.

Specifically:
- After each Anthropic API call, compute `estimated_usd = (input_tokens × input_price + output_tokens × output_price)` using current published rates.
- Publish as `lex_consultation_cost_usd_total{agent_id=...}` (Counter).
- Include `cost_breakdown_by_agent` in `ConsultResponse` for per-consultation transparency.
- Grafana dashboard aggregates daily cost and 7-day rolling average.
- Alert `DailyCostSpike` fires when daily cost exceeds 2× the 7-day average.

The `packages/finops` package is the designated home for cost utilities.
The Anthropic Admin API (programmatic billing access) is deferred to Fase 9.

---

## Alternatives considered

**Pull from Anthropic Admin API (billing endpoint):** More accurate but adds latency
and an outbound dependency on every request. Also not available for self-hosted or
local dev. Deferred to Fase 9 for production reconciliation.

**Log-based cost parsing:** Fragile, breaks if log format changes. Rejected.

---

## Consequences

- Cost figures are estimates — actual billing may differ by 1–3% due to Anthropic
  internal processing differences.
- Reconciliation workflow documented in `docs/cost-management.md`.
- Token prices must be updated manually in `packages/finops/src/.../pricing.py`
  when Anthropic changes pricing.
