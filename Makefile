.DEFAULT_GOAL := help
SHELL := /bin/bash

# ─── Variables ────────────────────────────────────────────────────────────────
UV      := uv
PNPM    := pnpm
DOCKER  := docker compose
DC_FILE := -f infra/docker-compose.yml
DC_DEV  := $(DC_FILE) -f infra/docker-compose.dev.yml
PYTHON  := $(UV) run python

.PHONY: help install lint format type-check test test-watch \
        eval eval-quick dev dev-detached down logs \
        build-images ingest-sample ingest-real qdrant-shell db-reset db-show

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
	$(UV) run pytest -x -q
	$(PNPM) exec vitest run

test-watch: ## Run tests in watch mode
	$(UV) run pytest -f &
	$(PNPM) exec vitest

# ─── Evals ────────────────────────────────────────────────────────────────────
eval: ## Run full evaluation suite
	$(UV) run python -m evals.runners.main --dataset evals/golden_dataset/

eval-quick: ## Run smoke eval set (≤5 cases, fast)
	$(UV) run python -m evals.runners.main --smoke

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
ingest-sample: ## Ingest fixture sample docs using local XML files (no network)
	$(PYTHON) scripts/ingest_sample.py

ingest-real: ## Ingest sample docs from live BOE + EUR-Lex APIs (requires network + ANTHROPIC_API_KEY)
	$(PYTHON) scripts/ingest_real.py

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
