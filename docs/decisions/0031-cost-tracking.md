# ADR 0031 — Cost Tracking End-to-End

- **Estado:** Accepted
- **Fecha:** 2026-05-12
- **Autores:** @ibernale
- **Fase:** 8.0 — Capa de control y observabilidad operacional

---

## Contexto

Hasta Fase 7, el coste de las llamadas a la Anthropic API no se mide de forma sistemática. Solo existe un campo `cost_estimate_usd` en la tabla `consultations` (apps/api/src/lex_agents_api/db.py), calculado ad-hoc sin tabla de precios versionada ni reconciliación externa.

Con la entrada en Fase 8, el sistema necesita responder a preguntas como:

- ¿Cuánto cuesta una consulta profunda vs. superficial?
- ¿Qué agente o fuente RAG genera el mayor coste?
- ¿Estamos dentro del presupuesto mensual?
- ¿Hay discrepancias entre lo que creemos que gastamos y lo que factura Anthropic?

El modelo debe ser defendible en un comité (cifras auditables) y accionable en tiempo real (alertas antes de superar presupuesto).

---

## Decisión

**Combinar tres fuentes para obtener coste autoritativo con reconciliación diaria:**

1. **Anthropic Usage & Cost API** — verdad última, en USD.
2. **Estimación local en tiempo real** — proxy entre fetches de la API.
3. **Reconciliación diaria** — detecta desviaciones sistemáticas.

---

## Fuente 1 — Anthropic Usage & Cost API

### Endpoints

```
GET /v1/organizations/usage_report/messages   # tokens por workspace/modelo/fecha
GET /v1/organizations/cost_report             # USD por workspace/fecha
```

### Configuración

- **Admin API key separada**: variable de entorno `ANTHROPIC_ADMIN_KEY` (distinta de `ANTHROPIC_API_KEY` usada por los agentes). La Admin key tiene permisos de lectura de usage; si se filtra, no puede generar consultas.
- **Workspace**: `lex-agents-dev` mapea al entorno MVP Fase 8. En Fase 9 se crean workspaces separados por entorno (dev/staging/prod).
- **Sync**: job nightly a las **06:00 UTC**, persiste en tabla `cost_daily` (ver schema abajo).

### Schema tabla `cost_daily`

```sql
CREATE TABLE cost_daily (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,          -- YYYY-MM-DD
    workspace       TEXT NOT NULL,
    model           TEXT NOT NULL,
    tokens_input    INTEGER NOT NULL DEFAULT 0,
    tokens_output   INTEGER NOT NULL DEFAULT 0,
    tokens_cached   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    source          TEXT NOT NULL,          -- 'anthropic_api' | 'local_estimate'
    fetched_at      TEXT NOT NULL,          -- ISO-8601 UTC
    UNIQUE(date, workspace, model, source)
);
```

---

## Fuente 2 — Estimación local en tiempo real

### Mecanismo

Cada llamada LLM captura en el span de Langfuse (ADR 0030):
- `tokens_input`, `tokens_output`, `tokens_cached`, `model`

El coste se estima aplicando la tabla de precios versionada `config/anthropic_prices.yaml`.

### Schema de `config/anthropic_prices.yaml`

```yaml
# Precios en USD por millón de tokens (MTok)
# Fuente: https://www.anthropic.com/pricing — actualizar via PR
# Versión: 1.0 — 2026-05-12
models:
  claude-opus-4-7:
    input_per_mtok: 15.00
    output_per_mtok: 75.00
    cached_per_mtok: 1.50       # cache read (10% del input)
    cache_write_per_mtok: 18.75 # cache write (125% del input)
  claude-sonnet-4-6:
    input_per_mtok: 3.00
    output_per_mtok: 15.00
    cached_per_mtok: 0.30
    cache_write_per_mtok: 3.75
  claude-haiku-4-5-20251001:
    input_per_mtok: 0.80
    output_per_mtok: 4.00
    cached_per_mtok: 0.08
    cache_write_per_mtok: 1.00

discounts:
  batch_api: 0.50              # 50% descuento en Batch API
```

**Política de cambios:** la tabla es parte del repositorio git. Cambios de precios se introducen vía PR con revisión, no como configuración de runtime. Esto garantiza trazabilidad del impacto de cambios de precio en histórico.

### Fórmula de estimación por llamada

```python
cost = (
    tokens_input  * prices[model]["input_per_mtok"]  / 1_000_000
  + tokens_output * prices[model]["output_per_mtok"] / 1_000_000
  + tokens_cached * prices[model]["cached_per_mtok"] / 1_000_000
)
```

Los tokens de escritura de caché (`cache_write`) se contabilizan separadamente cuando Langfuse los expone.

---

## Fuente 3 — Reconciliación diaria

### Job nightly (`06:00 UTC`)

1. Fetch de Anthropic API para el día anterior.
2. Suma de estimaciones locales del mismo día desde `cost_daily` (source='local_estimate').
3. Cálculo del diff relativo:

```python
diff_pct = abs(api_usd - local_usd) / api_usd * 100
```

4. Si `diff_pct > 5%` → alerta (canal de logs + métrica Prometheus `cost_reconciliation_diff_pct`).
5. La cifra **oficial** es siempre la de Anthropic API. La estimación local es solo proxy en tiempo real.

### Causas esperadas de diff aceptable (<5%)

- Latencia de hasta 24h en la API de Anthropic para reportar algunos tokens.
- Diferencias de redondeo en tokens cacheados.
- Llamadas de herramientas (tool use) con contabilización especial.

---

## Granularidad mínima del tracking

Cada registro de coste debe poder asociarse a:

| Dimensión | Fuente | Ejemplo |
|---|---|---|
| `trace_id` | Langfuse | `trc_abc123` |
| `agent` | Nombre del span | `legal_planner`, `mercantil_specialist` |
| `model` | Campo de la llamada | `claude-opus-4-7` |
| `context_type` | Tag en el trace | `consultation`, `document_analysis`, `lemaj_nightly`, `prompt_evolution` |
| `rag_source` | Tag en el trace | `boe`, `eurlex`, `cendoj` |

Esta granularidad permite responder: *"el 40% del coste de las consultas profundas viene del agente Planner usando Opus"*.

---

## Fuera de scope en Fase 8

- **Coste de infraestructura** (Qdrant, Dagster, Postgres, Docker): sistema local sin billing cloud.
- **Coste de embeddings** (BGE-M3 corre local): sin coste por token.
- **Fase 9**: cuando el sistema se despliegue corporativamente, se añade tracking de infra cloud (EC2/GKE, almacenamiento, red) con la misma arquitectura de reconciliación.

---

## Alternativas consideradas

| Alternativa | Razón de descarte |
|---|---|
| **Solo Anthropic API** | Sin visibilidad en tiempo real entre fetches diarios. No permite alertas en caliente. |
| **Solo estimación local** | Imprecisa a largo plazo (precios cambian, errores de redondeo acumulados). No auditable ante terceros. |
| **LangSmith cost tracking** | Cloud-only; los datos de uso salen del perímetro local. |
| **OpenCost / infracost** | Diseñados para coste cloud, no para tokens LLM. |

---

## Consecuencias

**Positivas:**
- Visibilidad en tiempo real del coste por consulta, sin esperar al ciclo diario de la API.
- Cifra oficial auditada por Anthropic, defendible en cualquier comité.
- Alertas automáticas si la estimación local diverge (señal de bug en el tracking).
- La tabla de precios en git crea historial de cuándo cambiaron los precios y su impacto en coste histórico.

**Negativas / Riesgos:**
- Mantener `config/anthropic_prices.yaml` actualizada requiere atención cada vez que Anthropic cambia precios.
- El diff >5% puede dispararse legítimamente cuando Anthropic introduce nuevas features de contabilización (herramientas, imágenes, etc.).

**Deuda técnica aceptada:**
- Tracking de cache_write tokens pendiente de que Langfuse lo exponga en la API de spans.
- Dashboard Grafana de coste por agente se implementa en sub-fase 8.1.

---

## Referencias

- [Anthropic API Usage Reporting](https://docs.anthropic.com/en/api/usage-reporting)
- [ADR 0030](0030-llm-observability-platform.md) — Langfuse como plataforma de observabilidad
- [ADR 0035](0035-immutable-audit-trail.md) — Audit trail de alertas de coste
- `config/anthropic_prices.yaml` — tabla de precios (creada en sub-fase 8.1)
