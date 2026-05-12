# ADR 0034 — Política de Retención de Logs y Trazas

- **Estado:** Accepted
- **Fecha:** 2026-05-12
- **Autores:** @ibernale
- **Fase:** 8.0 — Capa de control y observabilidad operacional

---

## Contexto

Con la integración de Langfuse (ADR 0030), el sistema comenzará a almacenar traces completos de cada consulta, incluyendo el prompt enviado al LLM, la respuesta, y el contexto RAG recuperado. Estos datos tienen valor operacional (debugging, evaluación) pero también implican riesgos de privacidad: pueden contener datos personales residuales si el usuario incluye información en su consulta.

Los datos almacenados en el sistema en Fase 8 incluyen:

| Tipo | Ubicación | ¿Puede contener PII? |
|---|---|---|
| Traces Langfuse | Langfuse Postgres | Sí (prompts con texto del usuario) |
| Métricas Prometheus | Prometheus TSDB | No (solo números agregados) |
| Audit trail | SQLite `audit_trail` | Mínimo (user_id, emails de actores) |
| Feedback de usuario | SQLite `user_feedback` | Bajo (texto libre opcional) |
| Audit samples | SQLite `audit_samples` | Sí (query + respuesta) |
| Costes y usage | SQLite `cost_daily` | No |
| Contenido raw de documentos subidos | Eliminado en pipeline | N/A (nunca persiste) |

El RGPD establece el principio de **limitación de conservación** (art. 5.1.e): los datos personales no se conservarán más tiempo del necesario. Aunque el sistema es local-only en Fase 8, el diseño debe respetar este principio para facilitar la auditoria en Fase 9.

---

## Decisión

**Política de retención escalonada por tipo de dato y sensibilidad**, documentada en `docs/legal/data-retention.md` para auditoría.

---

## Tabla de retención

| Tipo de dato | Retención | Acción al expirar | Justificación |
|---|---|---|---|
| Traces Langfuse (full payload) | **90 días** | Agregados conservados; traces eliminados | PII residual en prompts; 90d suficiente para debugging y evaluación |
| Métricas Prometheus | **365 días** con downsampling tras 30d | Downsampling a resolución 1h; eliminación tras 365d | Sin PII; valor analítico a largo plazo |
| Audit trail admin | **Indefinido** | No se elimina | Evidencia de gobernanza; puede necesitarse en auditoría regulatoria |
| User feedback | **Indefinido** | No se elimina | Insumo para mejoras; texto libre sin PII estructurado |
| Audit samples (query + respuesta) | **365 días** | Eliminación completa | PII residual posible; 365d cubre ciclos anuales de revisión |
| Costes (Anthropic API + estimación local) | **Indefinido** | No se elimina | Datos agregados; necesarios para reporting financiero histórico |
| Contenido raw de docs subidos | **NUNCA persiste** | Eliminación tras pipeline (ya en Fase 7) | Documentos pueden contener información confidencial cliente |
| Datos de usuarios (`users.db`) | Mientras `active=1` + **2 años** tras desactivación | Eliminación o anonimización | Mínima retención para auditoría de accesos históricos |

---

## Implementación por tipo

### Traces Langfuse — 90 días

Langfuse OSS incluye una política de retención configurable en el panel de administración (`Settings → Data Retention → 90 days`). El sistema elimina automáticamente traces con `timestamp < NOW() - 90d`.

**Qué se conserva tras la eliminación:**
- Métricas agregadas (número de llamadas, coste total, scores de evaluators) — permanecen en Prometheus.
- Metadata anonimizada (modelo, agente, latencia, tokens) — en `cost_daily`.

**Dato retenido más allá de 90 días: ninguno** con payload completo de prompt/respuesta.

### Métricas Prometheus — 365 días con downsampling

Configuración en `infra/prometheus/pipeline_rules.yml`:

```yaml
# Downsampling tras 30 días: resolución de 1 hora en lugar de 15 segundos
- record: job:legal_query_latency_p95:1h
  expr: histogram_quantile(0.95, rate(legal_query_latency_bucket[1h]))

# Retención total en prometheus.yml
storage.tsdb.retention.time: 365d
```

El downsampling reduce el storage ~95% para métricas históricas sin perder tendencias.

### Audit trail — Indefinido

El audit trail es evidencia de gobernanza. Su eliminación podría ser, en sí misma, una infracción de gobernanza. Se conserva indefinidamente y se exporta periódicamente a backup inmutable (sub-fase 8.2).

No contiene datos sensibles del usuario final: registra **acciones de administradores**, no contenido de consultas jurídicas.

### Audit samples — 365 días

Los audit samples contienen query + respuesta completa y pueden incluir PII residual. Se eliminan a los 365 días. Las métricas derivadas (scores de evaluación, estadísticas de calidad) se conservan indefinidamente en Prometheus.

```sql
-- Job nightly: eliminar audit_samples con más de 365 días
DELETE FROM audit_samples WHERE sampled_at < datetime('now', '-365 days');
```

### Documentos subidos — Eliminación inmediata

Establecido en Fase 7: los documentos subidos se procesan en pipeline y se eliminan del storage temporal inmediatamente. No se almacenan chunks del documento en Qdrant con datos del usuario; solo se usa para análisis contextual en el turno de la consulta.

---

## Cumplimiento RGPD

Aunque el sistema es local-only en Fase 8 (no hay transferencia de datos a terceros), el diseño cumple:

- **Art. 5.1.c — Minimización**: solo se almacenan los datos necesarios para cada finalidad.
- **Art. 5.1.e — Limitación de conservación**: plazos definidos y aplicados automáticamente.
- **Art. 25 — Privacy by design**: la retención se configura al desplegar, no como tarea manual posterior.
- **Art. 32 — Seguridad**: los datos más sensibles (traces Langfuse) son los de menor retención.

La política completa se documenta en `docs/legal/data-retention.md` para facilitar revisión por parte del DPO en Fase 9.

---

## Alternativas consideradas

| Alternativa | Razón de descarte |
|---|---|
| **Retención uniforme 30 días** | Demasiado agresiva para audit trail de gobernanza y feedback de usuarios. |
| **Retención uniforme 1 año** | Excesiva para traces con PII potencial. 90 días cubre el 99% de los casos de debugging. |
| **Retención indefinida de todo** | Incompatible con principio de minimización RGPD. Coste creciente de storage. |
| **Anonimización en lugar de eliminación** | Aumenta complejidad (¿qué es PII en consultas jurídicas?). La eliminación es más sencilla y segura. |

---

## Consecuencias

**Positivas:**
- Política explícita y auditable por el DPO o regulador.
- El downsampling de Prometheus reduce storage ~95% sin pérdida de información útil a largo plazo.
- La eliminación automática de traces en Langfuse no requiere operación manual.

**Negativas / Riesgos:**
- Los 90 días de retención de traces pueden ser insuficientes si un incidente de calidad se detecta tarde. Mitigación: LeMAJ nightly detecta degradaciones antes de 30 días.
- La retención indefinida del audit trail puede generar un volumen no trivial a largo plazo. Mitigación: el schema es compacto (~200 bytes por registro); a 1000 operaciones admin/mes son ~2.4MB/año.

**Deuda técnica aceptada:**
- El job nightly de eliminación de `audit_samples` se implementa en sub-fase 8.2.
- `docs/legal/data-retention.md` se crea con el contenido completo para revisión DPO en sub-fase 8.2.

---

## Referencias

- RGPD Art. 5.1.c, 5.1.e, Art. 25, Art. 32
- [ADR 0030](0030-llm-observability-platform.md) — Langfuse y retención de traces
- [ADR 0035](0035-immutable-audit-trail.md) — Audit trail y su política de retención
- `docs/legal/data-retention.md` — Documento legible por DPO (creado en sub-fase 8.2)
