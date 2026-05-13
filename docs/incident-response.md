# Incident Response — lex-agents v0.4.0

Structured response procedures for the five most likely production incidents.
Each section follows the format: **Severity → Detection → Containment →
Investigation → Resolution → Post-mortem**.

---

## IR-001: Service Unavailable

**Severity:** P1 — all user-facing functionality is down  
**Owner:** on-call operator or admin  
**Target resolution time:** < 30 min

### Detection

- Grafana alert `ServiceDown` fires
- `GET /health` returns non-200 or times out
- In-app critical notification appears in admin bell

### Containment

No kill switch needed — if the service is already down, users already get errors.
Focus on recovery.

### Investigation

```bash
# 1. Which container is unhealthy?
docker compose ps

# 2. Recent logs from unhealthy container
docker compose logs api --tail=100
docker compose logs qdrant --tail=50

# 3. Resource pressure?
docker stats --no-stream

# 4. Disk full?
df -h
```

### Resolution

```bash
# Restart unhealthy service
docker compose restart api
# or
docker compose restart qdrant

# If persistent, rebuild:
docker compose up --build -d api
```

### Post-mortem triggers

- If the outage exceeded 15 minutes, write a post-mortem note.
- Check if the alert fired within 5 minutes of the issue starting.

---

## IR-002: Anthropic API Degradation

**Severity:** P2 — consultations fail or are very slow  
**Owner:** admin  
**Target resolution time:** < 60 min (mostly external dependency)

### Detection

- Grafana alert `AnthropicApiErrorRate` fires (> 5% error rate over 10 min)
- Consultation responses return `500` or time out
- Cost metric flatlines while request rate stays normal (cached responses not used)

### Containment

```bash
# Engage global kill switch to give users a clear 503 instead of hanging requests
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "Anthropic API degradation — IR-002"}' \
  http://localhost:8000/api/v1/admin/system/kill/global
```

### Investigation

```bash
# Test Anthropic API directly (check their status page first)
curl -s https://status.anthropic.com/api/v2/status.json | jq .status

# Check API key validity (not rate-limited/revoked)
curl -s https://api.anthropic.com/v1/models \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H "anthropic-version: 2023-06-01" | jq .

# Check error distribution in logs
docker compose logs api | grep "anthropic" | grep -iE "error|rate.limit|overload" | tail -30
```

### Resolution

- If Anthropic incident: wait and release kill switch when resolved.
- If rate limit: review MAX_TOKENS_PER_CONSULTATION and request volume.
- If key revoked: rotate key (runbook §9.1).

---

## IR-003: Cost Runaway

**Severity:** P2 — financial risk  
**Owner:** admin  
**Target resolution time:** < 30 min

### Detection

- Grafana alert `DailyCostSpike` fires (daily cost > 2× 7-day average)
- In-app critical notification created automatically

### Containment

```bash
# Engage kill switch immediately if cost is still accelerating
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "IR-003: Cost runaway — investigation in progress"}' \
  http://localhost:8000/api/v1/admin/system/kill/global
```

### Investigation

```bash
# Identify top-cost consultations
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/ops/cost-breakdown?top=20&window_minutes=120' | jq

# Check if a new prompt version was recently deployed
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/governance/proposals?status=approved&limit=5' | jq

# Check for abnormal request patterns (same user, high frequency)
docker compose logs api | grep "POST /api/v1/consult" | awk '{print $NF}' | sort | uniq -c | sort -rn | head -20
```

### Resolution

- If caused by a prompt change: rollback (runbook §4.5) and release kill switch.
- If caused by abuse: block the user (edit USER_CREDENTIALS), release kill switch.
- If false positive: verify with Anthropic Console, release kill switch.

---

## IR-004: Hallucination Surge

**Severity:** P2 — output quality degraded, regulatory risk  
**Owner:** admin  
**Target resolution time:** < 2 hours

### Detection

- Grafana alert `VerificationFailedRateHigh` fires (> 10% `status=red` over 1h)
- Manual review of audit samples reveals incorrect citations

### Containment

```bash
# Engage kill switch for affected agent (not global, other agents still work)
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "IR-004: Hallucination surge on specialist_banking"}' \
  http://localhost:8000/api/v1/admin/system/kill/specialist_banking
```

### Investigation

```bash
# Identify failing consultations
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/audit?verification_status=red&limit=50' | jq \
  '.[] | {consultation_id, agent_id, query_preview, created_at}'

# Check recent prompt evolution
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/governance/proposals?status=approved&limit=3' | jq

# Run evals on suspect prompt
make eval-quick
```

### Resolution

- If prompt regression: rollback (runbook §4.5).
- If data quality issue (source returning bad content): pause source (runbook §3.2).
- If systemic: engage global kill switch and escalate to legal team for review.

### Post-mortem triggers

- All P2 hallucination incidents require a post-mortem note.
- Review citation verification thresholds (ADR-0008).

---

## IR-005: Potential PII Breach

**Severity:** P1 — regulatory obligation (RGPD Art. 33)  
**Owner:** admin + DPO  
**Target resolution time:** Containment < 15 min; AEPD notification < 72h

### Detection

- Manual discovery or automated alert from log scanner
- User report of seeing another user's data
- Abnormal audit trail entry pattern

### Containment — IMMEDIATE

```bash
# 1. Engage global kill switch RIGHT NOW
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "IR-005: SECURITY INCIDENT — potential PII breach — containment"}' \
  http://localhost:8000/api/v1/admin/system/kill/global

# 2. Do NOT delete any logs or data (evidence preservation)
```

### Investigation

```bash
# Export full audit trail for forensic analysis
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail/export?format=json&days=7' \
  -o "ir005_audit_$(date +%Y%m%d_%H%M%S).json"

# Check consultation responses for PII in output
# (consultation data is stored in consultations.db — request DBA review)

# Check PII redactor was active in logs
docker compose logs api | grep "pii_redacted" | tail -20
```

### Escalation

1. Notify DPO (Santander) immediately with preliminary findings.
2. Preserve all logs and database snapshots.
3. Do NOT release the kill switch until DPO clearance.
4. If breach confirmed: AEPD notification within 72 hours of detection.

### Resolution

- Only release kill switch after DPO confirms containment.
- Patch the root cause before re-enabling.
- Document full timeline in audit trail.

---

## Severity matrix

| Severity | Examples                        | Engage kill switch? | Escalate DPO? | SLA      |
| -------- | ------------------------------- | ------------------- | ------------- | -------- |
| P1       | Service down, PII breach        | Yes (if service up) | If PII        | < 30 min |
| P2       | Cost spike, hallucination surge | Agent-level first   | No            | < 2h     |
| P3       | Tier 2 alert, source error      | No                  | No            | < 24h    |
| P4       | Audit samples high, PRs pending | No                  | No            | Next day |
