# Runbook

> **Status:** Placeholder — to be completed in Fase 1.

## Table of contents

1. [Service startup and shutdown](#service-startup-and-shutdown)
2. [Ingestion procedures](#ingestion-procedures)
3. [Qdrant operations](#qdrant-operations)
4. [Common failures and remediation](#common-failures-and-remediation)
5. [On-call escalation](#on-call-escalation)

---

## Service startup and shutdown

_To be completed in Fase 1._

```bash
# Start all services
make dev

# Stop all services
make down
```

## Ingestion procedures

_To be completed in Fase 2._

## Qdrant operations

```bash
# Open interactive Qdrant shell
make qdrant-shell

# Reset all vector data (DESTRUCTIVE)
make db-reset
```

## Common failures and remediation

_To be completed in Fase 1._

## On-call escalation

_To be defined._
