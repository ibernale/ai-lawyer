# lex-agents

Multi-agent platform for specialised legal consultation. MVP: EU+ES banking
regulation, sources BOE and EUR-Lex.

## Prerequisites

| Tool | Version |
|------|---------|
| Docker + Docker Compose | ≥ 27 |
| [uv](https://github.com/astral-sh/uv) | ≥ 0.4 |
| Node.js | ≥ 20 |
| pnpm | ≥ 9 |

## Arrancar en local

```bash
# 1. Clonar y entrar al directorio
git clone https://github.com/ibernale/ai-lawyer.git && cd ai-lawyer

# 2. Copiar el fichero de variables de entorno y editar los valores
cp .env.example .env
# → Edita ANTHROPIC_API_KEY con tu clave real

# 3. Instalar dependencias (Python + Node)
make install

# 4. Arrancar todos los servicios (Qdrant + API + Web + OTel + Jaeger)
make dev

# 5. Verificar que la API responde
curl http://localhost:8000/health
# Esperado: {"status":"healthy","version":"...","deps_status":{...}}

# 6. Abrir la interfaz web
open http://localhost:3000
# Badge verde → backend healthy

# 7. Ver trazas distribuidas (opcional)
open http://localhost:16686
```

> Si Qdrant no está en estado `healthy` tras 30 s, ejecuta `make logs`
> para ver los logs de todos los servicios.

## Quick start (Fase 1 — after bootstrap)

```bash
# 1. Copy secrets template and fill in values
cp .env.example .env

# 2. Install all dependencies
make install

# 3. Start services (Qdrant + API + Web)
make dev
```

The API will be available at `http://localhost:8000` and the web UI at
`http://localhost:3000`.

## Key commands

| Command | Description |
|---------|-------------|
| `make dev` | Start all services (foreground) |
| `make test` | Run pytest + vitest |
| `make eval-quick` | Run smoke eval set |
| `make lint` | Lint Python + TS |
| `make type-check` | mypy --strict on Python packages |

Full list: `make help`.

## Project structure

```
apps/api/          FastAPI backend
apps/web/          Next.js frontend
packages/agents/   Orchestrator + specialist agents
packages/rag/      Contextual retrieval + hybrid search + reranking
packages/verifier/ Claim-level citation verifier
packages/ingest/   BOE + EUR-Lex scrapers and pipeline
packages/shared/   Shared types, clients, logging
evals/             Golden dataset, runners, reports
infra/             Docker Compose, Grafana dashboards
docs/decisions/    Architecture Decision Records (ADRs)
```

## Architecture & decisions

See [`docs/architecture.md`](docs/architecture.md) and
[`docs/decisions/`](docs/decisions/).

## Contributing

See [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)
and skill [`project-conventions`](.claude/skills/project-conventions/SKILL.md).
