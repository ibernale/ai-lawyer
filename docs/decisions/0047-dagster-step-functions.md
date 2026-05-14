# ADR 0047 — Migración de Dagster a AWS Step Functions + Lambda

**Estado:** Accepted  
**Fecha:** 2026-05-14  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0029 (FinOps), 0036 (multi-account), 0042 (persistencia), 0043 (CDK)  
**Sub-fase:** 9.2

---

## Contexto

Las fases 6–7 implementaron los pipelines de ingesta legal (BOE, EUR-Lex) usando
**Dagster** como orquestador. En Fase 9.2 la aplicación migra a AWS y los pipelines
deben ejecutarse en la infra cloud sin mantener un proceso Dagster permanente.

Las opciones evaluadas son:

| Opción | Descripción |
|---|---|
| 1 | **Dagster Cloud** (managed SaaS) |
| 2 | **Dagster self-hosted** en ECS Fargate |
| 3 | **AWS Step Functions + Lambda** nativo |

### Opción 1 — Dagster Cloud

- Pro: cero operaciones, UI completa, integración CI/CD.
- Contra: coste mensual (~$300–800/mes para el tier necesario), datos de auditoría de
  pipeline salen del perímetro Santander, dependencia de vendor externo para un pipeline
  de ingestión que corre una vez al día.

### Opción 2 — Dagster self-hosted en ECS

- Pro: reutiliza todo el código de `packages/pipeline/` sin cambios, UI disponible.
- Contra: ECS task para Dagster daemon + webserver siempre activo (~$60/mes en dev),
  complejidad operacional (daemon, scheduler, webserver, código repo de sincronización),
  Dagster no aporta valor diferencial para pipelines simples de 6 pasos secuenciales.

### Opción 3 — Step Functions + Lambda (seleccionada)

- Pro:
  - **Sin coste en reposo**: Lambda y Step Functions se cobran por invocación, no por
    tiempo activo. El pipeline diario de BOE/EUR-Lex cuesta < $0.10/mes en dev.
  - **AWS-nativo**: integración directa con S3, Secrets Manager, CloudWatch, EventBridge.
  - **Suficiente para nuestros pipelines**: 6 pasos secuenciales (fetch → parse → chunk →
    contextualize → embed → index). No hay grafos complejos de dependencias.
  - **Retry y error handling** declarativos en la State Machine.
  - **Trazabilidad** vía X-Ray y CloudWatch Logs sin código adicional.
- Contra:
  - Código Dagster (`packages/pipeline/`) no se reutiliza directamente: hay que portar
    la lógica de cada asset a un handler Lambda/ECS.
  - Pérdida de la UI de Dagster (asset catalog, timeline). Se reemplaza por CloudWatch
    Dashboard + Step Functions console.
  - Pasos de embedding y contextualización superan el timeout de Lambda (15 min) bajo
    carga; se ejecutan como ECS RunTask on-demand.

---

## Decisión

**Opción 3: Step Functions + Lambda nativo.**

### Arquitectura de pipelines

#### Pipeline `LexAgentsIngestBoe` (y `LexAgentsIngestEurlex`)

```
EventBridge Cron (0 6 * * ? *)
  └── Step Function: LexAgentsIngestBoe
        ├── FetchRaw          Lambda  — descarga XML desde BOE API, guarda en S3 raw
        ├── ParseCanonical    Lambda  — parsea XML → canonical JSON en S3 canonical
        ├── ChunkDocument     Lambda  — chunking legal → chunks JSON en S3 canonical
        ├── ContextualizeChunks  Lambda  — llama Anthropic API, escribe contextos
        ├── EmbedChunks       ECS RunTask  — Voyage AI batch embed (> 15 min posible)
        └── IndexToQdrant     ECS RunTask  — upsert a Qdrant (usa misma imagen API)
```

Pasos `EmbedChunks` e `IndexToQdrant` se implementan como `ECS:runTask` en la State
Machine porque pueden superar el timeout de Lambda de 15 minutos con documentos grandes.

#### Idempotencia

DynamoDB tabla `lex-agents-${env}-pipeline-state`:
- Clave primaria: `doc_id` (e.g., `BOE-A-2019-3814`)
- Atributos: `stage`, `s3_raw_key`, `s3_canonical_key`, `chunks_count`, `embedded_at`,
  `indexed_at`, `last_run_id`
- Cada Lambda comprueba si el paso ya completó para este `doc_id` antes de procesar.

#### Mapping de assets Dagster → Step Functions

| Asset Dagster (`packages/pipeline/`) | Handler AWS (`packages/pipeline_aws/`) | Runtime |
|---|---|---|
| `raw.py` — `raw_boe_documents` | `fetch_handler.py` | Lambda 512 MB, 5 min |
| `canonical.py` — `canonical_boe` | `parse_handler.py` | Lambda 512 MB, 5 min |
| `chunked.py` — `chunked_boe` | `chunk_handler.py` | Lambda 512 MB, 5 min |
| `contextualized.py` — `contextualized_boe` | `contextualize_handler.py` | Lambda 1 GB, 15 min |
| `embedded.py` — `embedded_boe` | `embed_handler.py` | ECS RunTask |
| `indexed.py` — `indexed_boe` | `index_handler.py` | ECS RunTask |

Los sensores Dagster (`sensors/format_change.py`) no se migran en Fase 9.2; se sustituyen
por EventBridge rules estáticas. Los sensores dinámicos (detección de cambio de formato) se
consideran para Fase 10.

#### Assets stub (no activos en dev)

Los siguientes assets de `packages/pipeline/` eran stubs y permanecen como stubs también
en `packages/pipeline_aws/`:
- CENDOJ (fuente judicial)
- Fuentes comerciales (Westlaw, Aranzadi) — RED, no activar hasta acuerdo de licencia

---

## Consecuencias

### Positivas

- Coste de pipeline < $1/mes en dev con Step Functions Express Workflows.
- Retries automáticos con backoff exponencial, sin código extra.
- X-Ray tracing distribuido de extremo a extremo (ingest → API → consulta).
- EventBridge permite añadir más triggers (S3 events, webhooks) sin cambios en la
  State Machine.

### Negativas / mitigaciones

- **Sin UI de Dagster**: mitigado con CloudWatch Dashboard `LexAgents-Pipeline` que
  muestra executions, failures, duración por step.
- **Porte de código**: `packages/pipeline/` se convierte en código legacy. Se mantiene
  para desarrollo local (`make ingest-sample` sigue funcionando). En Fase 10 se puede
  eliminar.
- **Lambda cold start** en `FetchRaw`: aceptable (~300ms) dado que el pipeline corre
  una vez al día fuera de horario.

### No cambia

- La lógica de parsing, chunking, contextualización y embedding es idéntica; solo cambia
  el entorno de ejecución (Lambda/ECS vs Dagster asset).
- `packages/ingest/` (BoeSource, EurlexSource, LegalChunker, Contextualizer, etc.) no se
  toca: los handlers Lambda los importan directamente.
- `make ingest-sample` sigue funcionando localmente llamando a `scripts/ingest_sample.py`.

---

## Referencias

- ADR 0042 — S3 buckets `lex-agents-raw-${env}`, `lex-agents-canonical-${env}`
- ADR 0043 — CDK TypeScript para `PipelineStack`
- [AWS Step Functions pricing](https://aws.amazon.com/step-functions/pricing/)
- [Comparison: Dagster vs Step Functions for batch pipelines](https://dagster.io/blog/dagster-aws-step-functions)
