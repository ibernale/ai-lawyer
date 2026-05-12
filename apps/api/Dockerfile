FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv

FROM base AS deps
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/
COPY packages/agents/pyproject.toml packages/agents/
COPY packages/rag/pyproject.toml packages/rag/
COPY packages/verifier/pyproject.toml packages/verifier/
COPY packages/ingest/pyproject.toml packages/ingest/
COPY packages/pipeline/pyproject.toml packages/pipeline/
COPY packages/memory/pyproject.toml packages/memory/
COPY packages/evals_advanced/pyproject.toml packages/evals_advanced/
COPY packages/audit/pyproject.toml packages/audit/
COPY apps/api/pyproject.toml apps/api/
COPY evals/pyproject.toml evals/
RUN uv sync --frozen --no-dev --package lex-agents-api

FROM base AS development
WORKDIR /app
COPY --from=deps /app/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"
# source code mounted at runtime via volume
CMD ["uvicorn", "lex_agents_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM python:3.12-slim AS runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=deps /app/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"
COPY packages/shared/src packages/shared/src
COPY apps/api/src apps/api/src
ARG COMMIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV COMMIT_SHA=$COMMIT_SHA BUILD_TIME=$BUILD_TIME
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "lex_agents_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
