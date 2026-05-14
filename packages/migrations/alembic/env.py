"""Alembic async migration environment.

Supports two modes:
1. Local dev: DATABASE_URL env var → direct asyncpg connection.
2. AWS: DATABASE_URL not set → fetch credentials from Secrets Manager using IAM auth.

Usage:
    # Local (DATABASE_URL already set)
    alembic upgrade head

    # AWS (reads /lex-agents/${ENV}/db/app-user from Secrets Manager)
    DATABASE_URL=... alembic upgrade head
    # or
    AWS_REGION=eu-west-1 LEX_ENV=dev alembic upgrade head
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from logging.config import fileConfig
from typing import Any

import boto3
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

logger = logging.getLogger("alembic.env")

# ---------------------------------------------------------------------------
# Alembic Config object
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# We do not use declarative metadata — all DDL is in raw SQL migration scripts.
target_metadata = None


# ---------------------------------------------------------------------------
# Database URL resolution
# ---------------------------------------------------------------------------

def _get_database_url() -> str:
    """Resolve DATABASE_URL from env or Secrets Manager."""
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url

    # AWS path: read from Secrets Manager
    env = os.environ.get("LEX_ENV", "dev")
    region = os.environ.get("AWS_REGION", "eu-west-1")
    secret_name = f"/lex-agents/{env}/db/app-user"

    logger.info("DATABASE_URL not set, fetching from Secrets Manager: %s", secret_name)
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    secret: dict[str, Any] = json.loads(response["SecretString"])

    host = secret["host"]
    port = secret.get("port", 5432)
    username = secret["username"]
    password = secret["password"]
    dbname = secret.get("dbname", "postgres")

    return f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{dbname}"


# ---------------------------------------------------------------------------
# Offline migrations (generate SQL without connecting)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout."""
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (connect and apply)
# ---------------------------------------------------------------------------

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = _get_database_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
