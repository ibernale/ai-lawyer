"""Dagster ConfigurableResources wrapping external clients."""

from __future__ import annotations

import os
from typing import Generator

import structlog
from dagster import ConfigurableResource, InitResourceContext

logger: structlog.BoundLogger = structlog.get_logger(__name__)


class AnthropicResource(ConfigurableResource):
    """Wraps anthropic.Anthropic — injects api_key from config or env."""

    api_key: str = ""

    def get_client(self) -> object:
        from anthropic import Anthropic  # type: ignore[import-untyped]

        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        return Anthropic(api_key=key)


class QdrantResource(ConfigurableResource):
    """Wraps QdrantClient — injects url and optional api_key."""

    url: str = "http://localhost:6333"
    api_key: str = ""
    collection_name: str = "lex_legal_docs"

    def get_client(self) -> object:
        from qdrant_client import QdrantClient  # type: ignore[import-untyped]

        return QdrantClient(
            url=self.url,
            api_key=self.api_key or None,
        )


class EmbedderResource(ConfigurableResource):
    """Wraps BgeM3Embedder — lazy-loaded, shared across materializations."""

    model_name: str = "BAAI/bge-m3"
    batch_size: int = 32

    def get_embedder(self) -> object:
        from lex_agents_ingest.embedder import BgeM3Embedder

        return BgeM3Embedder(
            model_name=self.model_name,
            batch_size=self.batch_size,
        )
