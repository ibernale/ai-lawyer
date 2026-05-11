# Runbook

## Table of contents

1. [Service startup and shutdown](#service-startup-and-shutdown)
2. [Branch protection (manual setup)](#branch-protection-manual-setup)
3. [Ingestion procedures](#ingestion-procedures)
4. [Qdrant operations](#qdrant-operations)
5. [Common failures and remediation](#common-failures-and-remediation)
6. [On-call escalation](#on-call-escalation)

---

## Service startup and shutdown

```bash
# Start all services in foreground (logs visible)
make dev

# Start all services in background
make dev-detached

# Stop all services
make down

# Tail logs
make logs
```

Services started: `qdrant` (6333), `api` (8000), `web` (3000),
`otel-collector` (4317/4318), `jaeger` (16686).

### Startup health check

```bash
# API health
curl http://localhost:8000/health

# Qdrant direct
curl http://localhost:6333/readyz

# Jaeger UI
open http://localhost:16686
```

---

## Branch protection (manual setup)

> **Action required:** Apply the following settings in GitHub after the
> first push to `main`. This cannot be automated via config files.

### Steps

1. Go to **github.com/ibernale/ai-lawyer → Settings → Branches**
2. Click **Add branch protection rule**
3. Branch name pattern: `main`
4. Enable the following:
   - ✅ **Require a pull request before merging**
     - ✅ Require approvals: **1**
     - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ **Require status checks to pass before merging**
     - ✅ Require branches to be up to date
     - Add required status checks (after first CI run):
       - `lint-py`
       - `typecheck-py`
       - `test-py`
       - `lint-web`
       - `typecheck-web`
       - `test-web`
       - `secrets-scan`
   - ✅ **Do not allow bypassing the above settings**
   - ✅ **Restrict who can push to matching branches** (optional: add team)
   - ❌ Allow force pushes (leave unchecked)
   - ❌ Allow deletions (leave unchecked)
5. Click **Create**

See ADR `docs/decisions/0004-cicd-strategy.md` for rationale.

---

## Ingestion procedures

### Fixture sample (offline, no network required)

```bash
make ingest-sample
# Ingests docs/sources/fixtures/*.xml into Qdrant
# Required: Qdrant running (make dev-detached)
```

### Live BOE + EUR-Lex (requires network + ANTHROPIC_API_KEY)

```bash
make ingest-real
# Calls live APIs; generates embeddings via BGE-M3; stores in Qdrant
# Takes ~5–15 min depending on corpus size
```

### Verify ingestion

```bash
curl http://localhost:6333/collections/lex_agents_v1/points/count
# Returns: {"result":{"count":<N>},...}
```

---

## Qdrant operations

```bash
# Open interactive Qdrant shell
make qdrant-shell

# Reset all vector data (DESTRUCTIVE — prompts for confirmation)
make db-reset

# Backup Qdrant snapshot
docker compose -f infra/docker-compose.yml exec qdrant \
  curl -X POST http://localhost:6333/collections/lex_agents_v1/snapshots

# Restore from snapshot (replace <snapshot_name>)
docker compose -f infra/docker-compose.yml exec qdrant \
  curl -X PUT \
    "http://localhost:6333/collections/lex_agents_v1/snapshots/recover" \
    -H "Content-Type: application/json" \
    -d '{"location":"file:///qdrant/snapshots/lex_agents_v1/<snapshot_name>"}'
```

---

## Rotate API keys

### Anthropic API key

1. Generate a new key in the Anthropic console.
2. Update `.env`: `ANTHROPIC_API_KEY=<new_key>`
3. Restart the API container: `docker compose -f infra/docker-compose.yml restart api`
4. Verify: `curl http://localhost:8000/health` → `anthropic_api: ok`

### JWT secret

1. Generate a strong secret: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update `.env`: `JWT_SECRET=<new_secret>`
3. All existing tokens are **immediately invalidated**; active sessions must re-authenticate.
4. Restart the API container.

### Internal auth users

Edit `AUTH_USERS_JSON` in `.env` (JSON array of `{username, password_hash, role}`):

```bash
# Generate bcrypt hash for new user
python -c "from passlib.hash import bcrypt; print(bcrypt.hash('your_password'))"
```

---

## Common failures and remediation

| Symptom | Likely cause | Remediation |
|---------|-------------|-------------|
| `api` exits on startup | `QDRANT_URL` not reachable | Ensure `qdrant` service is healthy first; check `QDRANT_URL` in `.env` |
| `health` returns `anthropic_api: not_configured` | `ANTHROPIC_API_KEY` empty | Set key in `.env` |
| `otel-collector` crash-loops | Jaeger not ready | Jaeger starts slower; collector will retry — usually self-resolves in 30s |
| Docker build fails on `uv sync` | No internet or cache miss | Run `make build-images` with `--no-cache` or ensure network access |
| `401 Unauthorized` on `/api/v1/*` | Token expired or `auth_enabled=false` missing | Re-authenticate via `POST /auth/token`; for dev set `AUTH_ENABLED=false` in `.env` |
| `429 Too Many Requests` | Rate limit exceeded (30 req/min on `/consult`) | Wait 60 s; adjust limit in `settings.py` if running load tests |
| Qdrant returns empty results | Collection not indexed | Run `make ingest-sample` or `make ingest-real` |
| Export .docx fails with 404 | Consultation not persisted yet | Background save is async; wait 1–2 s and retry |
| Grafana shows no data | Prometheus not scraping | Check `infra/prometheus.yml` target is `api:8000`; verify `make dev` started prometheus |

---

## Observability

```bash
# Grafana dashboard (rate, latency, errors)
make grafana
# → http://localhost:3001 (admin/admin)

# Prometheus raw metrics
curl http://localhost:9090/metrics

# Jaeger distributed traces
open http://localhost:16686

# Structured logs (JSON)
docker compose -f infra/docker-compose.yml logs api | jq .
```

---

## On-call escalation

Internal Slack: `#lex-agents-oncall`. Escalate to:

1. **API errors / 5xx surge** → check `/metrics` rate_5xx panel → check `make logs`
2. **Anthropic API unavailable** → fallback: return cached consultation if trace_id known; otherwise 503
3. **Qdrant data loss** → restore from snapshot (see above); re-index if no snapshot available
4. **PII in logs** → verify `enable_pii_redaction=true` in prod (`ENV=prod` in `.env`); rotate affected logs
