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

_To be completed in Fase 2._

---

## Qdrant operations

```bash
# Open interactive Qdrant shell
make qdrant-shell

# Reset all vector data (DESTRUCTIVE — prompts for confirmation)
make db-reset
```

---

## Common failures and remediation

| Symptom | Likely cause | Remediation |
|---------|-------------|-------------|
| `api` exits on startup | `QDRANT_URL` not reachable | Ensure `qdrant` service is healthy first; check `QDRANT_URL` in `.env` |
| `health` returns `anthropic_api: not_configured` | `ANTHROPIC_API_KEY` empty | Set key in `.env` |
| `otel-collector` crash-loops | Jaeger not ready | Jaeger starts slower; collector will retry — usually self-resolves in 30s |
| Docker build fails on `uv sync` | No internet or cache miss | Run `make build-images` with `--no-cache` or ensure network access |

---

## On-call escalation

_To be defined in Fase 5 (alerting + PagerDuty integration)._
