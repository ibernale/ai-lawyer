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

| Symptom                                          | Likely cause                                   | Remediation                                                                             |
| ------------------------------------------------ | ---------------------------------------------- | --------------------------------------------------------------------------------------- |
| `api` exits on startup                           | `QDRANT_URL` not reachable                     | Ensure `qdrant` service is healthy first; check `QDRANT_URL` in `.env`                  |
| `health` returns `anthropic_api: not_configured` | `ANTHROPIC_API_KEY` empty                      | Set key in `.env`                                                                       |
| `otel-collector` crash-loops                     | Jaeger not ready                               | Jaeger starts slower; collector will retry — usually self-resolves in 30s               |
| Docker build fails on `uv sync`                  | No internet or cache miss                      | Run `make build-images` with `--no-cache` or ensure network access                      |
| `401 Unauthorized` on `/api/v1/*`                | Token expired or `auth_enabled=false` missing  | Re-authenticate via `POST /auth/token`; for dev set `AUTH_ENABLED=false` in `.env`      |
| `429 Too Many Requests`                          | Rate limit exceeded (30 req/min on `/consult`) | Wait 60 s; adjust limit in `settings.py` if running load tests                          |
| Qdrant returns empty results                     | Collection not indexed                         | Run `make ingest-sample` or `make ingest-real`                                          |
| Export .docx fails with 404                      | Consultation not persisted yet                 | Background save is async; wait 1–2 s and retry                                          |
| Grafana shows no data                            | Prometheus not scraping                        | Check `infra/prometheus.yml` target is `api:8000`; verify `make dev` started prometheus |

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

## Fase 6 operations

### Re-materializar un asset Dagster

```bash
# Re-run a single Dagster asset (e.g., after source changes or failures)
dagster asset materialize --select boe_raw

# Or for a group
dagster asset materialize --select boe_raw+ eur_lex_raw+

# Via Dagster UI: http://localhost:3002 → Assets → select asset → Materialize
# Monitor run in UI; GREEN = success, RED = inspect logs for root cause.
```

**Common failure causes:**

- Source HTTP 429 → check `RATE_LIMIT_DELAY` env var; increase if needed.
- Qdrant connection refused → ensure `make dev` is running; check `docker compose ps`.
- Checksum mismatch on canonical layer → re-run from raw: `dagster asset materialize --select boe_canonical`.

---

### Revisar PR de prompt evolution

Prompt evolution PRs are opened automatically by the reflection pipeline (ADR 0021).
**They require human review before merge — CODEOWNERS prevents auto-merge.**

Checklist:

1. Read the PR body: verify the failing case and `diff_text` match.
2. Check the regression simulation table: all 5 neighbor cases must pass (✅). If any fail (❌), close PR.
3. Run locally:
   ```bash
   uv run python -m lex_agents_evals_advanced.reflection run --dry-run --specialist <branch_name>
   ```
4. Confirm the mandatory IA caveat and jurisdictional caveats are intact in the proposed prompt.
5. Confirm the change does not expand specialist scope beyond ADRs 0010–0021.
6. Assign to a qualified lawyer for content review.
7. Merge only after all checklist items are confirmed.

---

### Añadir patrón procedimental

```bash
# Open the seed SQL for editing
make procedural-edit
# → opens packages/memory/src/lex_agents_memory/data/seed.sql in $EDITOR

# Add INSERT INTO procedural_patterns (pattern_id, jurisdiction, ...) VALUES (...)
# See existing rows for format reference

# Apply migration to development DB
make procedural-apply

# Validate
uv run pytest packages/memory/tests/test_procedural.py -q

# Open PR with @ibernale review required (CODEOWNERS enforces)
```

**Invariant:** procedural patterns are read-only at runtime. No code path writes to `procedural.db`
after seeding. If you need to modify a pattern, update `seed.sql` and reseed.

---

### Abrir nueva fuente documental

Follow ADR 0018 (8-step checklist):

1. **Identify source**: confirm URL stability, license, and update frequency.
2. **Create scraper** in `packages/ingest/src/lex_agents_ingest/sources/<source>.py`.
3. **Create raw Dagster asset** in `packages/pipeline/src/lex_agents_pipeline/assets/sources.py`.
4. **Create canonical asset** with normalized `LegalDocument` schema.
5. **Add tests** in `packages/ingest/tests/` with at least 3 fixture documents.
6. **Manual GREEN gate**: run `dagster asset materialize --select <source>_canonical` and verify
   ≥ 10 documents indexed in Qdrant with expected chunk count.
7. **Add to CI** by including the asset in `.github/workflows/ingest.yml`.
8. **Update `docs/sources/`** with source metadata (maintainer, license, update schedule).

Never add a source that is not GREEN-gated — AMBER/RED sources degrade retrieval quality.

---

## On-call escalation

Internal Slack: `#lex-agents-oncall`. Escalate to:

1. **API errors / 5xx surge** → check `/metrics` rate_5xx panel → check `make logs`
2. **Anthropic API unavailable** → fallback: return cached consultation if trace_id known; otherwise 503
3. **Qdrant data loss** → restore from snapshot (see above); re-index if no snapshot available
4. **PII in logs** → verify `enable_pii_redaction=true` in prod (`ENV=prod` in `.env`); rotate affected logs
