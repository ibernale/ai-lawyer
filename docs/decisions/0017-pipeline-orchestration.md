# ADR 0017 — Orquestación del pipeline de ingesta con Dagster

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale

---

## Context

lex-agents v0.1.0 ingesta documentos mediante scripts CLI puntuales
(`scripts/ingest_sample.py`, `scripts/ingest_real.py`). Para soportar la expansión
a 9 fuentes GREEN (ADR 0011) con actualizaciones incrementales, re-materialización
selectiva y linaje completo, los scripts deben evolucionar a un sistema de
orquestación declarativa.

Los requisitos concretos son:

1. **Incremental**: solo procesar documentos nuevos o modificados.
2. **Linaje completo**: trazar qué chunks dependen de qué documento canónico y qué
   versión del modelo de embedding.
3. **Re-materialización selectiva**: cambiar el prompt de contextualización o el
   modelo de embedding debe invalidar automáticamente únicamente los assets
   afectados, sin re-descargar ni re-parsear.
4. **Scheduling declarativo**: BOE diario, EUR-Lex semanal, etc., sin gestionar cron
   externo.
5. **Fail fast**: si una fuente cambia su formato, el pipeline debe fallar en el
   asset afectado, no en silencio.
6. **Observabilidad**: métricas de ingesta visibles en Grafana existente.

---

## Alternativas evaluadas

### Opción A: Apache Airflow

Airflow organiza el trabajo en DAGs de **tareas**. Las dependencias se expresan como
`task_a >> task_b`. No existe el concepto nativo de "asset": un DAG no sabe qué datos
produce cada tarea ni en qué estado se encuentran.

Para implementar re-materialización selectiva con Airflow habría que:

- Añadir lógica custom de versionado en cada tarea
- Gestionar el estado de los artefactos en un almacén externo (S3, base de datos propia)
- Escribir sensores ad-hoc para detectar cambios en formato o modelo

Airflow requiere un metastore externo (PostgreSQL en producción), un scheduler
separado, y tiene overhead operacional significativo para el volumen de lex-agents.

**Descartado**: task-first no asset-first. El modelo mental del equipo es jurídico:
"el RD 84/2015 cambió → recalcular dependencias", no "la tarea ingest_boe falló".

### Opción B: Prefect

Prefect es más moderno que Airflow y soporta flows con dependencias declarativas.
Tiene un concepto de "artifacts" en Prefect Cloud, pero no en el OSS server.

Para re-materialización selectiva, Prefect requiere lógica custom similar a la de
Airflow: el framework no razona nativamente sobre "este artefacto tiene una versión
anterior porque cambió el modelo de embedding".

Prefect es flexible y menos opinionado, lo que es una ventaja para casos generales
pero una desventaja cuando el patrón de datos es claro: `raw → canonical → chunks →
vectors → índice`. La flexibilidad se convierte en código de infraestructura que el
equipo debe mantener.

**Descartado**: flexible pero no asset-first. La flexibilidad no compensa el
overhead de implementar versioning y linaje manualmente.

### Opción C: Dagster

Dagster trata cada unidad de trabajo como un **software-defined asset**: un nodo del
grafo que produce datos con una identidad (`AssetKey`), una versión (`DataVersion`),
dependencias declaradas sobre otros assets, y checks de calidad (`AssetCheckSpec`).

Esto encaja directamente con el modelo de datos de lex-agents:

| Entidad lex-agents          | Asset Dagster                                             |
| --------------------------- | --------------------------------------------------------- |
| Documento raw descargado    | `boe_raw`, `eurlex_raw`, …                                |
| Documento canónico parseado | `boe_canonical`, …                                        |
| Chunks                      | `boe_chunked` (versión = hash del config del chunker)     |
| Chunks contextualizados     | `boe_contextualized` (versión = hash del prompt)          |
| Vectores                    | `boe_embedded` (versión = nombre del modelo de embedding) |
| Índice Qdrant               | `boe_indexed`                                             |

Cuando cambia la versión de `boe_contextualized` (porque cambió el prompt), Dagster
marca automáticamente `boe_embedded` y `boe_indexed` como _stale_ sin necesidad de
código adicional. El job `reindex_all_job` puede re-materializar únicamente los
assets afectados.

---

## Decision

Usar **Dagster** como orquestador del pipeline de ingesta.

### Estructura del paquete

```
packages/pipeline/src/lex_agents_pipeline/
├── assets/       # raw, canonical, chunked, contextualized, embedded, indexed
├── resources/    # AnthropicResource, QdrantResource, EmbedderResource
├── sensors/      # source_format_change_sensor, embedding_model_change_sensor
├── schedules/    # cron por fuente (BOE diario, EUR-Lex semanal, …)
├── jobs/         # ingest_boe_job, ingest_all_job, reindex_all_job, …
└── definitions.py
```

### Re-materialización selectiva via DataVersion

Cada asset declara su `DataVersion` de forma que:

- `*_chunked`: versión = hash del config del chunker (`max_tokens`, `overlap`)
- `*_contextualized`: versión = sha256 del archivo de prompt activo
- `*_embedded`: versión = nombre del modelo de embedding
- `*_indexed`: sin versión propia — depende del upstream

Cuando un `DataVersion` cambia, Dagster marca los assets downstream como _stale_
y el sensor `embedding_model_change_sensor` lanza automáticamente `reindex_all_job`.

### Idempotencia

Cada asset es idempotente: si el documento ya existe con el mismo checksum, se
marca como `skipped` sin re-procesar. Esto permite relanzar jobs sin efectos
secundarios.

### Asset checks

Cada asset expone al menos un check:

- `*_raw`: `n_docs >= 1`, `no_zero_byte_files`
- `*_canonical`: `parse_error_rate < 5%`
- `*_indexed`: `qdrant_collection_exists`, `points_count > 0`

Los checks fallidos se muestran en la Dagster UI y generan alertas Prometheus.

### Sensor de cambio de formato

`source_format_change_sensor` (cadencia horaria) hace HEAD requests a cada fuente y
compara el fingerprint (ETag/Last-Modified/hash de contenido) contra el valor
guardado. Si detecta un cambio, crea un GitHub Issue via `gh issue create` para que
el equipo revise el parser antes de que el pipeline falle en producción.

### Integración con observabilidad existente

Dagster expone métricas en `/metrics` en formato Prometheus. El servicio Dagster en
Docker Compose es scrapeado por Prometheus existente. Un dashboard Grafana dedicado
(`infra/grafana/dashboards/pipeline.json`) muestra documentos procesados, tasa de
errores, latencia de ingesta y assets stale pendientes.

### Compatibilidad hacia atrás

Los scripts `scripts/ingest_sample.py` y `scripts/ingest_real.py` siguen funcionando.
El target `make ingest-sample` se actualiza para llamar a Dagster, pero el pipeline
subyacente (`packages/ingest/`) no cambia. Los nuevos assets son wrappers del código
existente, no reemplazos.

---

## Consequences

**Positivo:**

- Linaje visual en la Dagster UI: desde un chunk indexado se puede navegar hasta el
  documento raw, la versión del prompt y el modelo de embedding
- Re-materialización selectiva sin código de infraestructura ad-hoc
- Scheduling declarativo coexiste con el scheduler externo (no se necesita cron)
- Los asset checks documentan los contratos de calidad de los datos

**Negativo/Riesgos:**

- Dagster añade dependencias (`dagster`, `dagster-webserver`) que aumentan el tamaño
  de la imagen Docker del pipeline
- La curva de aprendizaje del modelo asset-first es mayor que la de scripts simples;
  el equipo necesita entender `DataVersion`, `AssetCheckSpec`, y `ConfigurableResource`
- El metastore SQLite (para dev) no escala para producción; se necesitará PostgreSQL
  cuando el volumen de runs sea elevado

**Neutral:**

- Dagster no gestiona los datos en sí: los artefactos intermedios (raw, canonical,
  chunks, vectors) siguen en el filesystem local (`data/`). En producción, esto
  debería migrarse a un almacén persistente (S3, NFS), lo que Dagster soporta
  nativamente vía `IOManager`.
