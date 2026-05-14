"""AWS Secrets Manager wrapper for lex-agents.

Provides a simple synchronous helper used at startup (settings load) and
an async helper for runtime use. Falls back gracefully when boto3 is
unavailable (local dev without AWS credentials).

Secret naming convention
------------------------
    /lex-agents/{env}/{name}

Examples:
    /lex-agents/dev/db/app-user      → Aurora credentials
    /lex-agents/dev/anthropic-key    → Anthropic API key
    /lex-agents/dev/voyage-key       → Voyage AI API key

Usage
-----
    from lex_agents_shared.secrets import get_secret_dict, get_secret_str

    creds = get_secret_dict("/lex-agents/dev/db/app-user")
    api_key = get_secret_str("/lex-agents/dev/anthropic-key")
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, cast

import structlog

logger: structlog.BoundLogger = structlog.get_logger(__name__)

_REGION = os.environ.get("AWS_REGION", "eu-west-1")
_LEX_ENV = os.environ.get("LEX_ENV", "dev")


def _secret_name(name: str) -> str:
    """Resolve a short name to the full Secrets Manager path."""
    if name.startswith("/"):
        return name
    return f"/lex-agents/{_LEX_ENV}/{name}"


@lru_cache(maxsize=32)
def get_secret_string(secret_id: str, *, region: str = _REGION) -> str:
    """Return the raw secret string for *secret_id* (cached per process).

    Args:
        secret_id: Full Secrets Manager ARN or name (or short name without
                   leading slash, which will be prefixed with
                   ``/lex-agents/{LEX_ENV}/``).
        region: AWS region override.

    Raises:
        RuntimeError: When boto3 / AWS credentials are unavailable.
        botocore.exceptions.ClientError: On AWS API errors (e.g. not found).
    """
    full_name = _secret_name(secret_id)
    try:
        import boto3  # lazy import — not required for local dev
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=full_name)
        value: str = response["SecretString"]
        logger.info("secret_fetched", secret=full_name)
        return value
    except ImportError as exc:
        raise RuntimeError(
            f"boto3 is not installed. Cannot fetch secret '{full_name}'. "
            "Install boto3 or set the value via environment variable."
        ) from exc


def get_secret_dict(
    secret_id: str,
    *,
    region: str = _REGION,
) -> dict[str, Any]:
    """Return the secret parsed as a JSON object (dict).

    Useful for database credentials secrets that contain ``host``,
    ``username``, ``password``, etc.
    """
    raw = get_secret_string(secret_id, region=region)
    return cast(dict[str, Any], json.loads(raw))


def get_secret_str(
    secret_id: str,
    *,
    region: str = _REGION,
) -> str:
    """Return the secret as a plain string (e.g. an API key)."""
    return get_secret_string(secret_id, region=region)


def build_aurora_dsn(
    secret_id: str = "db/app-user",  # noqa: S107 — AWS Secrets Manager path, not a password
    *,
    region: str = _REGION,
    asyncpg_dialect: bool = True,
) -> str:
    """Build a PostgreSQL DSN from a Secrets Manager credential secret.

    The secret must contain keys: ``host``, ``username``, ``password``.
    Optional keys: ``port`` (default 5432), ``dbname`` (default ``postgres``).

    Args:
        secret_id: Short name or full path of the credential secret.
        region: AWS region override.
        asyncpg_dialect: If True, prefix with ``postgresql://`` (asyncpg
                         native). If False, use ``postgresql+asyncpg://``
                         (SQLAlchemy dialect).

    Returns:
        Connection string suitable for asyncpg or SQLAlchemy.
    """
    creds = get_secret_dict(secret_id, region=region)
    host = creds["host"]
    port = creds.get("port", 5432)
    username = creds["username"]
    password = creds["password"]
    dbname = creds.get("dbname", "postgres")

    scheme = "postgresql" if asyncpg_dialect else "postgresql+asyncpg"
    return f"{scheme}://{username}:{password}@{host}:{port}/{dbname}"


def invalidate_cache() -> None:
    """Clear the in-process secret cache (useful in tests)."""
    get_secret_string.cache_clear()
