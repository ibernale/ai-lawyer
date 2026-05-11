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
    qdrant_collection: str = "lex_legal_docs"

    # RAG
    rag_top_k: int = 10
    embedder_model: str = "BAAI/bge-m3"
    reranker_enabled: bool = True
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "lex-agents-api"

    # Security
    jwt_secret: SecretStr = SecretStr("changeme-replace-in-prod")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours
    # JSON array of user objects: [{"username":"demo","password_hash":"bcrypt...","role":"analyst"}]
    auth_users_json: SecretStr = SecretStr(
        '[{"username":"demo","password_hash":"$2b$12$placeholder","role":"analyst"}]'
    )
    auth_enabled: bool = True  # set False only for local dev without auth

    # Consultation history
    consultation_db_path: str = "data/consultations.db"
    agents_package_enabled: bool = True

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
