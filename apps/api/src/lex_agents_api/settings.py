"""Application settings loaded from environment variables / .env file."""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Runtime environment
    env: Literal["dev", "staging", "prod"] = "dev"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Anthropic
    anthropic_api_key: SecretStr = SecretStr("")

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "lex-agents-api"

    # Security (placeholder until Fase 5)
    jwt_secret: SecretStr = SecretStr("changeme")

    # Build metadata (injected by Dockerfile ARG → ENV)
    commit_sha: str = "unknown"
    build_time: str = "unknown"
    version: str = "0.1.0"

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("qdrant_url")
    @classmethod
    def qdrant_url_must_be_set(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("QDRANT_URL must not be empty")
        return v

    @model_validator(mode="after")
    def prod_requires_anthropic_key(self) -> "Settings":
        if self.env == "prod" and not self.anthropic_api_key.get_secret_value().strip():
            raise ValueError(
                "ANTHROPIC_API_KEY is required when ENV=prod"
            )
        return self


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
