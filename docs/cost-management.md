# Cost Management — lex-agents v0.4.0

How costs are tracked, where to view them, and how to respond when
spending is anomalous.

---

## How costs are tracked

Each consultation response includes a `cost_breakdown_by_agent` field
containing the estimated USD cost per agent involved in the pipeline.
Costs are estimated from Anthropic's published token prices using the
input/output token counts returned by the API.

These costs are also published as Prometheus counters:

```
lex_consultation_cost_usd_total{agent_id="specialist_banking"}  0.0124
lex_consultation_cost_usd_total{agent_id="verifier"}             0.0031
```

Prometheus stores them cumulatively; use `increase()` or `rate()` for
time-windowed views.

---

## Viewing costs

### Grafana dashboard

`http://localhost:3001` → **lex-agents / Costs**

Key panels:
- **Daily cost (USD)** — bar chart of total daily spend
- **7-day rolling average** — baseline for anomaly detection
- **Cost by agent** — pie/bar of spend distribution across agents
- **Cost per consultation** — histogram of per-request cost distribution

### Prometheus direct queries

```promql
# Total cumulative cost
sum(lex_consultation_cost_usd_total)

# Cost in the last 24 hours
sum(increase(lex_consultation_cost_usd_total[24h]))

# Cost rate per hour (last 6h)
sum(rate(lex_consultation_cost_usd_total[1h])) * 3600

# Cost breakdown by agent (last 24h)
sum by (agent_id) (increase(lex_consultation_cost_usd_total[24h]))
```

### Per-consultation breakdown

```bash
# Via API
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/consult/<consultation_id> \
  | jq '.cost_breakdown_by_agent'
```

---

## Alert thresholds

| Alert           | Condition                              | Default threshold        |
|-----------------|----------------------------------------|--------------------------|
| `DailyCostSpike`| Daily cost > N × rolling 7d average   | N = 2 (configurable YAML)|

To change the multiplier, edit `infra/grafana/provisioning/alerting/tier1.yaml`
and restart Grafana.

---

## Reconciling drift

Drift is defined as: `|local_cost - anthropic_invoice_cost| / anthropic_invoice_cost > 5%`.

Possible causes:
- Cached responses served without calling the API (cost = 0 locally, billed externally)
- Token estimation differs from actual billing (Anthropic bills after processing)
- Retries counted once locally but multiple times by Anthropic

**Reconciliation workflow:**

1. Export local accumulated cost from Prometheus
2. Compare with invoice from Anthropic Console (`console.anthropic.com/billing`)
3. If drift > 5%:
   - Review top-cost consultations (`GET /api/v1/admin/ops/cost-breakdown?top=20`)
   - Check for any retries in logs (`docker compose logs api | grep retry`)
   - Verify no zero-cost cache hits are skewing the local metric
4. Document findings in the audit trail via a manual `system.cost.reconciliation` entry

---

## Responding to a cost spike

When the `DailyCostSpike` alert fires:

1. **Immediate triage** — is this legitimate demand or anomalous?
   - Check request rate vs. cost per request (if rate is normal but cost spiked, look at token counts)
   - Check if a new prompt version was deployed recently

2. **Isolate the cause:**
   ```bash
   # Top 20 most expensive consultations in last 2h
   curl -s -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/admin/ops/cost-breakdown?top=20&window_minutes=120' | jq
   ```

3. **If caused by a specific agent**, engage its kill switch:
   ```bash
   curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"engage": true, "reason": "Cost spike investigation: specialist_banking"}' \
     http://localhost:8000/api/v1/admin/system/kill/specialist_banking
   ```

4. **If systemic**, engage the global kill switch (see runbook §2.4)

5. Once resolved, release the kill switch and document the incident.

---

## Cost limits

Set `MAX_TOKENS_PER_CONSULTATION` in `.env` to cap the maximum tokens any
single consultation can consume. Requests exceeding this limit return a
`400 TOKEN_LIMIT_EXCEEDED` error before calling the Anthropic API.

Recommended starting value: `8000` tokens (approx. $0.05–0.10 per request).

---

## Anthropic Admin API (Fase 9)

Fase 9 will integrate with the [Anthropic Admin API](https://docs.anthropic.com/admin-api)
to pull official usage and billing data programmatically. See ADR-0029 for
the FinOps tracking decision.

This will enable:
- Real-time billing reconciliation
- Per-workspace spend tracking
- Automated budget enforcement
