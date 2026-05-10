---
name: security-and-pii
description: |
  Use this skill when implementing PII detection/redaction, secrets management,
  or security controls for lex-agents. Covers PII entity types for ES/EU
  context, redaction format, secrets hygiene, pre-commit and CI scanning hooks,
  and upcoming API/frontend security headers.
---

## PII entity types to detect and redact

| Type | Pattern / description | Redaction token |
|------|-----------------------|-----------------|
| DNI | 8 digits + letter (ES) | `[PII:DNI]` |
| NIE | X/Y/Z + 7 digits + letter | `[PII:NIE]` |
| NIF (empresa) | Letter + 8 digits | `[PII:NIF]` |
| IBAN (ES) | ES + 22 digits | `[PII:IBAN]` |
| Número de cuenta | 20-digit BBAN without IBAN prefix | `[PII:ACCOUNT]` |
| Número de tarjeta | 16-digit patterns (Luhn check) | `[PII:CARD]` |
| Email | RFC 5322 pattern | `[PII:EMAIL]` |
| Teléfono ES | +34 or 6/7/9 followed by 8 digits | `[PII:PHONE]` |
| Nombre propio (opcional) | NER-detected; configurable | `[PII:NAME]` |

## Redaction points

Apply redaction at:
1. **Query ingress** — before query reaches any agent or log
2. **Log emission** — `structlog` processor strips PII before any log sink
3. **Eval dataset** — no real client data in golden dataset

Redaction is **configurable** via `PII_REDACTION_ENABLED=true/false` env var.
Default: `true` in production, `false` in local dev.

## Secrets hygiene

- All secrets via environment variables. Never hardcode.
- `.env` is gitignored. `.env.example` is committed (no real values).
- `.env.example` documents every variable with type, example, and description.

```bash
# .env.example
ANTHROPIC_API_KEY=sk-ant-...       # Anthropic API key
QDRANT_URL=http://localhost:6333   # Qdrant instance URL
QDRANT_API_KEY=                    # Optional; leave empty for local
LOG_LEVEL=INFO                     # DEBUG | INFO | WARNING | ERROR
PII_REDACTION_ENABLED=true
```

## Pre-commit scanning

Both `gitleaks` and `detect-secrets` run on every commit (see `.pre-commit-config.yaml`).

- `gitleaks`: detects entropy-based secrets and known patterns
- `detect-secrets`: baseline in `.secrets.baseline`; update baseline with
  `detect-secrets scan > .secrets.baseline` when adding intentional test fixtures

If a scan blocks a commit incorrectly, add an inline `# pragma: allowlist secret`
comment for `detect-secrets` or `# gitleaks:allow` for gitleaks — never disable
the hook globally.

## CI pipeline scanning

In Fase 1 GitHub Actions CI:
- `gitleaks` runs on every push and PR
- `detect-secrets` diff-mode on changed files
- Trivy scans Docker images for CVEs (critical and high → CI red)

## API security headers (Fase 5)

When implementing:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy: default-src 'self'` (refine per app)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- Rate limiting: per-user IP token bucket, configurable via `RATE_LIMIT_RPM`

## What NOT to do

- Do not log raw query strings at INFO level (use DEBUG and enable only in dev)
- Do not include `Authorization` headers in error messages or logs
- Do not store API keys in Docker image layers (use runtime env injection)
- Do not commit `.env`, even in test branches
