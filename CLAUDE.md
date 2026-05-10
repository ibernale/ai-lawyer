# lex-agents

Plataforma multi-agente para consulta jurídica especializada (uso interno
banca). MVP: regulatorio bancario UE+ES, fuentes BOE + EUR-Lex.

## Principios no negociables
1. Toda afirmación normativa o jurisprudencial lleva cita verificable.
   Sin cita → el agente lo declara explícitamente.
2. Citas se verifican a nivel de claim contra el chunk indexado antes de
   devolver respuesta.
3. Borrador asistido por IA; requiere validación humana cualificada.

## Stack
Python 3.12 + FastAPI · Anthropic API · Qdrant · Next.js · Docker Compose.
Detalles y ADRs en `docs/decisions/`.

## Convenciones
Conventional Commits, trunk-based, idioma EN en código y commits, ES en
docs jurídicas. Detalles en skill `project-conventions`.

## Cómo trabajar
- Tareas grandes: empezar con plan mode (`/plan`).
- Exploración del repo: usar subagent `Explore`.
- Tareas especializadas: ver subagents en `.claude/agents/`.
- Operaciones repetidas: ver skills en `.claude/skills/`.

## Comandos
`make dev`, `make test`, `make eval-quick`, `make ingest-sample`.
Listado completo en `Makefile`.

## Sensibilidad
No commitear secretos, no logguear PII en claro, no incluir datos
internos Santander en el repo público hasta revisión.
