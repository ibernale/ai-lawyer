# packages/shared

Shared foundation for all lex-agents packages. Provides: Pydantic v2 domain
types (chunk metadata, citation mapping, verification report, query/response
contracts), a typed Anthropic API client wrapper with retry logic, a Qdrant
client factory, and the `structlog`-based logging configuration with PII
redaction middleware. All other packages depend on this one; it must have zero
circular dependencies.
