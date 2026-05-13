.DEFAULT_GOAL := help
SHELL := /bin/bash

# ─── Variables ────────────────────────────────────────────────────────────────
UV      := uv
PNPM    := pnpm
DOCKER  := docker compose
DC_FILE := -f infra/docker-compose.yml
DC_DEV  := $(DC_FILE) -f infra/docker-compose.dev.yml
PYTHON  := $(UV) run python

.PHONY: help install lint format type-check test test-cov test-watch \
        eval eval-quick dev dev-detached down logs \
        build-images ingest-sample ingest-real ingest-all dagster-ui \
        qdrant-shell db-reset db-show grafana \
        validate-knowledge procedural-edit

# ─── Help ─────────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ─── Install ──────────────────────────────────────────────────────────────────
install: ## Install all Python and Node dependencies
	$(UV) sync --all-packages
	$(PNPM) install
	pre-commit install

# ─── Lint & format ────────────────────────────────────────────────────────────
lint: ## Run ruff linter and prettier check
	$(UV) run ruff check .
	$(PNPM) exec prettier --check "**/*.{ts,tsx,js,jsx,json,yaml,md}"

format: ## Auto-fix ruff and prettier formatting
	$(UV) run ruff check --fix .
	$(UV) run ruff format .
	$(PNPM) exec prettier --write "**/*.{ts,tsx,js,jsx,json,yaml,md}"

type-check: ## Run mypy --strict on all Python packages
	$(UV) run mypy --strict packages/ apps/api/

# ─── Test ─────────────────────────────────────────────────────────────────────
test: ## Run full test suite (pytest + vitest)
	$(UV) run --extra dev --package lex-agents-agents pytest -x -q
	$(PNPM) exec vitest run

test-cov: ## Run pytest with coverage report (target ≥ 80%)
	$(UV) run --extra dev --package lex-agents-agents pytest \
		--cov=packages/agents/src \
		--cov=packages/verifier/src \
		--cov=packages/rag/src \
		--cov=packages/shared/src \
		--cov-report=term-missing \
		--cov-fail-under=80 \
		-q

test-watch: ## Run tests in watch mode
	$(UV) run --extra dev --package lex-agents-agents pytest -f &
	$(PNPM) exec vitest

# ─── Memory ───────────────────────────────────────────────────────────────────
validate-knowledge: ## Validate docs/knowledge/ YAML schemas
	$(UV) run --package lex-agents-memory python -m lex_agents_memory.semantic.validator

procedural-edit: ## Open procedural seed SQL for editing (opens editor, then commit + PR)
	@echo "Edit packages/memory/seed/procedural_patterns_seed.sql then: git add, git commit, gh pr create"
	$(EDITOR) packages/memory/seed/procedural_patterns_seed.sql

# ─── Evals ────────────────────────────────────────────────────────────────────
eval: ## Run full evaluation suite (30 cases)
	$(UV) run python -m evals run \
		--dataset evals/golden_dataset \
		--output evals/reports/$(shell date +%Y%m%dT%H%M%S)/

eval-quick: ## Run smoke eval set (~5 cases, ~30s)
	$(UV) run python -m evals run \
		--dataset evals/golden_dataset_smoke \
		--output evals/reports/smoke_$(shell date +%Y%m%dT%H%M%S)/

# ─── Development ──────────────────────────────────────────────────────────────
dev: ## Start all services in foreground (dev mode)
	$(DOCKER) $(DC_DEV) up

dev-detached: ## Start all services in background
	$(DOCKER) $(DC_DEV) up -d

down: ## Stop all services and remove containers
	$(DOCKER) $(DC_FILE) down

logs: ## Tail logs from all services
	$(DOCKER) $(DC_FILE) logs -f

# ─── Build ────────────────────────────────────────────────────────────────────
build-images: ## Build all Docker images
	$(DOCKER) $(DC_FILE) build

# ─── Data / ingestion ─────────────────────────────────────────────────────────
ingest-sample: ## Ingest fixture sample docs directly (BOE + EUR-Lex fixtures, no Dagster subprocess)
	$(UV) run python scripts/ingest_sample.py

ingest-real: ## Ingest from live BOE + EUR-Lex APIs via Dagster (requires ANTHROPIC_API_KEY)
	$(UV) run dagster job execute \
		-f packages/pipeline/src/lex_agents_pipeline/definitions.py \
		-j ingest_boe_job
	$(UV) run dagster job execute \
		-f packages/pipeline/src/lex_agents_pipeline/definitions.py \
		-j ingest_eurlex_job

ingest-all: ## Run all GREEN source ingest jobs via Dagster
	$(UV) run dagster job execute \
		-f packages/pipeline/src/lex_agents_pipeline/definitions.py \
		-j ingest_all_job

dagster-ui: ## Launch Dagster webserver at localhost:3002
	$(UV) run dagster dev \
		-f packages/pipeline/src/lex_agents_pipeline/definitions.py \
		--port 3002

# ─── Database / Qdrant ────────────────────────────────────────────────────────
qdrant-shell: ## Open a shell inside the qdrant container
	$(DOCKER) $(DC_FILE) exec qdrant sh

db-reset: ## Destroy and recreate Qdrant volumes (DESTRUCTIVE)
	@read -p "This will delete all indexed data. Continue? [y/N] " ans && [ "$$ans" = "y" ]
	$(DOCKER) $(DC_FILE) down -v
	$(DOCKER) $(DC_DEV) up -d qdrant
	@echo "Qdrant volumes reset."

db-show: ## Show recent consultations from SQLite history
	sqlite3 data/consultations.db "SELECT trace_id, substr(query,1,60), latency_ms FROM consultations ORDER BY created_at DESC LIMIT 10;"

grafana: ## Open Grafana dashboard in browser
	open http://localhost:3001

## ─── Admin user management ───────────────────────────────────────────────────
.PHONY: admin-bootstrap user-add

admin-bootstrap:
	@python scripts/admin_bootstrap.py --role admin

user-add:
	@python scripts/admin_bootstrap.py --role $(ROLE) --username $(USERNAME)
