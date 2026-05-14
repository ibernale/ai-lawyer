# Cost Model — lex-agents AWS (Fase 9.5)

> Referencia: ADR 0045 — Modelo de costes AWS
> Metodología: AWS Pricing Calculator + Cost Explorer actuals (pending first month)

---

## Estimación Mensual Baseline (dev environment)

| Servicio           | Componente                        | Estimado/mes (USD) | Notas                            |
| ------------------ | --------------------------------- | ------------------ | -------------------------------- |
| ECS Fargate        | API (1 task, 0.5 vCPU, 1GB)       | 15                 | 720h/mes FARGATE_SPOT ~70%       |
| ECS Fargate        | Web (1 task, 0.25 vCPU, 0.5GB)    | 6                  | FARGATE_SPOT ~70%                |
| ECS Fargate        | Qdrant (1 task, 0.5 vCPU, 1GB)    | 20                 | FARGATE estándar (EFS)           |
| ECS Fargate        | Langfuse (1 task, 0.5 vCPU, 1GB)  | 18                 | FARGATE estándar                 |
| Aurora PG          | Serverless v2, auto-pause dev     | 5-25               | 0-8 ACU, auto-pause 5min         |
| Aurora PG          | Langfuse cluster                  | 5-15               | 0-4 ACU, auto-pause 5min         |
| S3                 | raw + canonical + evals + backups | 3-8                | ~100GB estimado                  |
| S3                 | compliance-docs                   | 1                  | WORM, lifecycle Glacier@365d     |
| KMS                | CMK requests                      | 2-5                | ~100K requests/mes               |
| Secrets Manager    | 5 secrets, accesos diarios        | 1-2                |                                  |
| ALB                | lex-agents-dev + langfuse         | 18                 | 2 ALBs \* $9 base                |
| NAT Gateway        | 2 AZs                             | 65                 | $0.045/h _ 2 _ 720h              |
| EFS                | Qdrant + app-data + hf-cache      | 3-10               | ~50GB                            |
| CloudWatch         | Logs + Alarms + Dashboards        | 5-15               | 4 dashboards + 7 alarms          |
| Lambda             | evidence_collector (1x/day)       | < 1                | 256MB, 5min, 30 invocations/mes  |
| Cost Anomaly       | CE Anomaly Monitor                | 0                  | Free (incluido en Cost Explorer) |
| **TOTAL ESTIMADO** |                                   | **$167-222/mes**   | Pendiente actuals primer mes     |

> **Nota**: Los actuals de AWS Billing tienen un retraso de 24h. Para estimaciones en tiempo real,
> usar AWS Cost Explorer. El dashboard `lex-agents-dev-finops` muestra la métrica
> `EstimatedCharges` desde us-east-1 (única región donde AWS publica billing metrics).

---

## Optimizaciones Aplicadas en Fase 9.5

### 1. Fargate Spot para API y Web

- **Configuración**: `FARGATE_SPOT` weight=3, `FARGATE` base=1, weight=1
- **Ahorro estimado**: ~55-70% en tareas API y Web
- **Ahorro mensual**: ~$14-18/mes (dev environment)
- **Riesgo**: Interrupciones SPOT (mitigado con circuitBreaker + minHealthyPercent)

### 2. S3 Lifecycle Optimizados (raw-ingest)

|                    | Antes | Después | Ahorro                         |
| ------------------ | ----- | ------- | ------------------------------ |
| IA transition      | 90d   | 30d     | Ahorro de ~60 días en STANDARD |
| Glacier transition | 365d  | 90d     | Ahorro de ~275 días en IA      |

- **Ahorro estimado**: $1-3/mes (depende de volumen de objetos)

### 3. S3 Lifecycle Optimizados (canonical)

|               | Antes | Después | Ahorro                          |
| ------------- | ----- | ------- | ------------------------------- |
| IA transition | 180d  | 60d     | Ahorro de ~120 días en STANDARD |

- **Ahorro estimado**: $0.5-1.5/mes

### 4. CloudWatch Log Retention Reducida

| Log Group                         | Antes    | Después | Ahorro                          |
| --------------------------------- | -------- | ------- | ------------------------------- |
| ECS (`/lex-agents/dev/ecs`)       | 1 semana | 1 mes   | Sin cambio real (era muy corto) |
| Aurora (`/lex-agents/dev/aurora`) | 1 año    | 1 mes   | ~$2-5/mes en CW Logs storage    |
| Langfuse logs                     | 1 semana | 1 mes   | Sin cambio real                 |

### 5. Log Archive: Glacier@7d

- CloudTrail logs archivados a Glacier a los 7 días (antes: Glacier Instant Retrieval @365d)
- **Ahorro estimado**: $2-5/mes en log-archive account

**Ahorro total mensual estimado (Fase 9.5)**: ~$18-28/mes

---

## Proyección workloads-pre

Cuando se active la cuenta `workloads-pre`, los recursos adicionales esperados:

| Componente                      | Estimado/mes (USD) |
| ------------------------------- | ------------------ |
| KMS CMKs (pre)                  | 2-3                |
| NetworkSpokeStack (VPC, NAT GW) | 65                 |
| Aurora Serverless v2 (pre)      | 10-30              |
| S3 buckets (pre)                | 3-8                |
| ECR repos (pre)                 | 1-3                |
| **SUBTOTAL pre**                | **$81-109/mes**    |

La cuenta pre NO incluye ECS (no app deployed en Fase 9.5 — solo infraestructura).
Añadir ~$60-80/mes cuando se despliegue la aplicación en pre.

---

## Metodología de Medición de Coste por Consulta

### Fórmula

```
coste_por_consulta = (coste_anthropic + coste_qdrant + coste_aurora + coste_infra_prorrateado) / num_consultas
```

### Componentes

1. **Coste Anthropic**: `input_tokens * $0.003/1K + output_tokens * $0.015/1K` (Claude 3.5 Sonnet)
2. **Coste Qdrant**: prorrateado por número de requests (`cost_qdrant_task / queries_per_month`)
3. **Coste Aurora**: prorrateado por ACU-hora usada durante la consulta
4. **Coste infraestructura**: coste fijo mensual / consultas totales

### Métricas en Langfuse

Langfuse registra automáticamente:

- `input_tokens` y `output_tokens` por traza
- Latencia total de la consulta
- Coste calculado por modelo (configurable en Langfuse → Models)

### Benchmark target

| Fase          | Consultas/mes (target) | Coste/consulta (target) |
| ------------- | ---------------------- | ----------------------- |
| Fase 9 (dev)  | 500 (tests)            | < $0.05                 |
| Fase 10 (pre) | 5.000                  | < $0.03                 |
| Fase 11 (pro) | 50.000                 | < $0.02                 |

---

## Alertas de Coste Configuradas

| Alerta                  | Umbral                        | Canal                         |
| ----------------------- | ----------------------------- | ----------------------------- |
| Cost Anomaly Detection  | > $20 USD/día vs. media 7d    | SNS → Slack `#lex-agents-ops` |
| Cost Anomaly (% impact) | > 100% del average baseline   | SNS → Slack `#lex-agents-ops` |
| Budget alert (planned)  | > 80% del presupuesto mensual | Pendiente Fase 10             |
