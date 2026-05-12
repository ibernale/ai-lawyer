# ADR 0030 — Plataforma de observabilidad LLM

- **Estado:** Accepted
- **Fecha:** 2026-05-12
- **Autores:** @ibernale
- **Fase:** 8.0 — Capa de control y observabilidad operacional

---

## Contexto

El stack de observabilidad establecido en ADR 0005 cubre infraestructura general:
- **OTel + Jaeger**: trazas distribuidas HTTP/gRPC.
- **Prometheus + Grafana**: métricas de sistema y negocio.

Con la entrada en Fase 8, el sistema opera 9 fuentes de ingesta, 6 ramas especialistas, PMJ (Planner–Maker–Judge), LeMAJ (5-judge panel), y el bucle de evolución de prompts. Las necesidades de observabilidad ya no se cubren con trazas HTTP genéricas:

1. **Session replay agentic**: ver la conversación completa orquestador→especialista→juez en una sola vista.
2. **Prompt management**: versionar prompts, comparar versiones A/B, hacer rollback sin tener que ir a git.
3. **Evaluators integrados**: medir hallucination, caveat compliance, toxicity directamente sobre las trazas.
4. **Cost tracking nativo por trace**: saber cuánto cuesta cada consulta, desglosado por agente y modelo.
5. **Debugging multi-step**: Jaeger está diseñado para latencias HTTP, no para razonar sobre decisiones de un LLM en paso 7 de 12.

Se evalúan alternativas self-hostable para cumplir el requisito local-only de Fase 8 (sin datos LLM en proveedores cloud de terceros).

---

## Decisión

**Adoptar Langfuse OSS (MIT) self-hosted como plataforma principal de observabilidad de agentes LLM**, manteniendo OTel + Jaeger + Prometheus + Grafana como infraestructura complementaria.

La integración es **no-migratoria**: Langfuse se añade como destino adicional al colector OTel existente en `infra/otel-collector-config.yaml`. No reemplaza nada del stack actual.

---

## Arquitectura resultante

```
Agentes Python
    │
    ├─ OTel SDK (spans, traces)
    │       │
    │       ├─→ Jaeger          [trazas infra no-LLM: Dagster, ingesta, HTTP]
    │       └─→ Langfuse        [trazas LLM: agentes, prompts, evaluators, coste]
    │
    └─ Prometheus client        [métricas sistema y negocio agregadas]
            │
            └─→ Prometheus → Grafana
```

### Separación de responsabilidades

| Componente | Responsabilidad | Lo que NO hace |
|---|---|---|
| **Langfuse** | Traces de agentes LLM, prompt management, evaluators, session replay, cost tracking por trace | Métricas de sistema (CPU, RAM, conexiones) |
| **Jaeger** | Traces de infraestructura no-LLM: Dagster asset runs, jobs de ingesta, llamadas HTTP entre servicios | Replay de conversaciones agente |
| **Prometheus + Grafana** | Métricas de sistema y negocio (queries/día, coste agregado, latencia p95), alertas | Replay individual, gestión de prompts |
| **SigNoz / Loki** | Explícitamente **excluidos** en MVP — cobertura solapada con los anteriores, complejidad operacional innecesaria |

---

## Componentes de Langfuse utilizados

### 1. Tracing agentic

Cada consulta genera un `Trace` en Langfuse que agrupa:
- `Span` por agente invocado (OrchestratorV2, LegalPlanner, especialista X, LegalJudge, etc.).
- Inputs y outputs de cada paso.
- Tokens consumidos y modelo usado por span.
- `Session` agrupando todos los turns de una misma sesión de usuario.

### 2. Prompt management

- Prompts versionados en Langfuse (nombre, versión semántica, variables, etiquetas).
- Integración con el bucle de prompt evolution (ADR 0021): PROpener sube la propuesta como nueva versión de prompt; admin aprueba/rechaza en Langfuse UI antes de merge a git.
- A/B testing: dos versiones activas en producción con porcentaje configurable.
- Rollback instantáneo desde UI sin despliegue.

### 3. Evaluators integrados

Evaluators asíncronos que se ejecutan sobre traces almacenados:
- `hallucination_score`: detecta afirmaciones sin cita.
- `caveat_compliance`: verifica presencia del aviso IA obligatorio.
- `citation_recall`: comprueba que claims clave están soportados por chunks indexados.
- Custom evaluators para dominios jurídicos específicos.

Los resultados de evaluators se exponen en Grafana vía Langfuse metrics export.

### 4. Cost tracking nativo

Langfuse calcula coste por trace usando la tabla de precios configurada (ver ADR 0031).
Granularidad: por trace, por span (agente), por modelo, por tipo de contexto.

---

## Despliegue

### MVP (Fase 8): Postgres como backend

```yaml
# docker-compose.dev.yml — nuevo servicio langfuse
langfuse:
  image: langfuse/langfuse:latest
  environment:
    DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
    NEXTAUTH_SECRET: ${LANGFUSE_SECRET}
    SALT: ${LANGFUSE_SALT}
  ports:
    - "3001:3000"

langfuse-db:
  image: postgres:16
  environment:
    POSTGRES_DB: langfuse
    POSTGRES_USER: langfuse
    POSTGRES_PASSWORD: langfuse
```

Langfuse escucha en `http://localhost:3001`. UI accesible solo en red local.

### Producción (gate: >1M traces/mes): ClickHouse como backend

ClickHouse sustituye Postgres como storage analítico de Langfuse cuando el volumen lo justifique. La API y la integración SDK no cambian; solo la capa de persistencia.

### Integración OTel

```yaml
# infra/otel-collector-config.yaml — exporters adicionales
exporters:
  otlp/langfuse:
    endpoint: "http://langfuse:4318"
    headers:
      Authorization: "Bearer ${LANGFUSE_PUBLIC_KEY}"
```

---

## Alternativas consideradas

| Alternativa | Razón de descarte |
|---|---|
| **LangSmith** (LangChain) | Cloud-only sin opción self-hosted real. Lock-in a LangChain. Datos salen del perímetro local. |
| **Helicone** | Versión OSS muy limitada; funcionalidades clave solo en cloud. |
| **Arize Phoenix** | OSS activo pero menor madurez en prompt management y evaluators. Buena alternativa para Fase 9 si Langfuse no escala. |
| **Weights & Biases** | Enfocado en ML experiments, no en observabilidad operacional de agentes legales. Excesivo para el caso de uso. |
| **Solo Jaeger + Grafana** | Requeriría construir desde cero session replay, evaluators y prompt management. Coste de construcción > coste de integrar Langfuse OSS. |

---

## Consecuencias

**Positivas:**
- Session replay completo de conversaciones agente sin instrumentación adicional en el código de negocio.
- Prompt management con versionado y rollback elimina el riesgo de prompts rotos en producción.
- Evaluators asíncronos permiten medir calidad jurídica a escala sin coste en el hot path de la consulta.
- Licencia MIT: no hay dependencia de planes comerciales; el código fuente está disponible para fork si es necesario.

**Negativas / Riesgos:**
- Servicio adicional en `docker-compose`: 1 Postgres + 1 Langfuse añaden ~512MB RAM al entorno local.
- Curva de aprendizaje: el equipo debe familiarizarse con el modelo trace/span/session de Langfuse.
- La integración OTel con Langfuse está en beta; puede requerir ajustes en versiones futuras.

**Deuda técnica aceptada:**
- Migración Postgres→ClickHouse pendiente para escala. Gate: 1M traces/mes.
- Los evaluators custom para dominio jurídico necesitan calibración manual inicial.

---

## Referencias

- [Langfuse OSS GitHub](https://github.com/langfuse/langfuse) — MIT License
- [ADR 0005](0005-observability.md) — Stack de observabilidad base
- [ADR 0031](0031-cost-tracking.md) — Cost tracking end-to-end
- [ADR 0021](0021-prompt-evolution-policy.md) — Gobernanza evolución de prompts
