# ADR 0045 — Cost model: estimación de coste fase inicial AWS

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0029 (FinOps), 0036 (regiones), 0037 (multi-account), 0039 (Bedrock),
0040 (RAG), 0041 (networking), 0042 (persistencia), 0043 (CDK)  
**Sub-fases afectadas:** 9.1 – 9.5

---

## Contexto

Antes de comprometer recursos de implementación, se necesita una estimación conservadora
del coste mensual en AWS para la Fase 9. El modelo ayuda a:

1. Establecer expectativas con el patrocinador del proyecto en Santander.
2. Identificar los servicios con mayor coste para optimización prioritaria.
3. Definir alertas de coste realistas en el dashboard de FinOps (ADR 0029).

Las cifras son estimaciones conservadoras para un entorno `workloads-dev` activo, con
un equipo de 2-3 desarrolladores iterando diariamente. No incluyen workloads-pre ni
workloads-pro (Fase 10).

Precios basados en tarifas AWS eu-central-1 vigentes en mayo 2026. Todos los precios en USD.

---

## Estimación mensual: cuenta `workloads-dev`

### Compute y hosting

| Servicio                          | Especificación                                                       | Cálculo                                             | Coste/mes   |
| --------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------- | ----------- |
| **AgentCore Runtime**             | ~500 invocaciones/día × 30 días = 15.000 inv/mes; duración media 60s | $0.004/invoc + $0.00001/s = $60 + ~$60 tokens       | **$50–200** |
| **ECS Fargate — API**             | 2 tasks × 1 vCPU × 2 GB × 730h (spot ~70% tiempo)                    | 2 × ($0.04048/vCPU/h + $0.004445/GB/h) × 730h × 0.7 | **~$70**    |
| **ECS Fargate — Web**             | 2 tasks × 0.5 vCPU × 1 GB × 730h (spot ~70%)                         | 2 × ($0.02024/h + $0.002222/h) × 730h × 0.7         | **~$35**    |
| **Lambda — tools + ingest hooks** | ~500K invocaciones/mes; duración media 200ms; 512 MB                 | $0.20/1M inv + $0.0000166667/GB-s                   | **~$5**     |
| **NAT Gateway**                   | 3 AZs × 730h + ~50 GB datos/mes                                      | 3 × $0.045/h × 730 + 3 × $0.045/GB × 50/3           | **~$100**   |
| **Application Load Balancer**     | 1 ALB, ~1 LCU estimado                                               | $0.008/h × 730h + ~$5 LCU                           | **~$11**    |
| **CloudFront**                    | ~10 GB transferencia/mes; ~100K requests                             | $0.085/GB × 10 + $0.0075/10K req × 10               | **~$2**     |

**Subtotal compute: ~$273–423/mes**

### Datos

| Servicio                            | Especificación                                           | Cálculo                                           | Coste/mes            |
| ----------------------------------- | -------------------------------------------------------- | ------------------------------------------------- | -------------------- |
| **Aurora Serverless v2**            | 0.5–4 ACU avg (activo 10h/día, pausa restante)           | 4 ACU avg activo × $0.12/ACU/h × 300h activas/mes | **~$145**            |
| **Aurora storage**                  | ~10 GB datos + backups                                   | $0.10/GB/mes × 10 + PITR                          | **~$25**             |
| **S3 — raw + canonical**            | ~20 GB Standard + ~30 GB IA                              | $0.023/GB × 20 + $0.0125/GB × 30                  | **~$0.80** → **~$5** |
| **S3 — backups + WORM**             | ~5 GB Glacier                                            | $0.004/GB × 5                                     | **~$1**              |
| **AWS Backup**                      | Aurora snapshots cross-region                            | ~$0.02/GB/mes × 10 GB × 2 regiones                | **~$5**              |
| **SageMaker Serverless — bge-m3**   | ~1.000 embedding requests/mes × 512 tokens avg; 2 GB mem | $0.00008/GB-s; cold starts ignorados              | **~$10**             |
| **SageMaker Serverless — reranker** | ~500 reranking requests/mes                              | Similar a embeddings                              | **~$5**              |
| **ElastiCache Redis**               | POSTPONED Fase 9                                         | —                                                 | **$0**               |

**Subtotal datos: ~$196/mes**

### Networking

| Servicio                       | Especificación                       | Coste/mes                        |
| ------------------------------ | ------------------------------------ | -------------------------------- |
| **VPC Endpoints Interface**    | 8 endpoints × 3 AZs × $0.01/h × 730h | **~$175**                        |
| **Data transfer inter-region** | Backups S3 → eu-west-1: ~15 GB/mes   | $0.02/GB × 15 = **~$0.30**       |
| **Data transfer Internet**     | Egreso desde CloudFront: ~10 GB/mes  | Ya incluido en CloudFront arriba |

> ⚠️ Los VPC Endpoints son más caros de lo estimado inicialmente ($175 vs $20).
> Optimización: usar la cuenta `network` (ADR 0037) para centralizar endpoints compartidos
> entre workloads-dev y workloads-pre, reduciendo a ~$90/mes por cuenta.

**Subtotal networking: ~$90–175/mes** (con/sin centralización en cuenta network)

### LLM Inference (variable)

| Modelo                             | Uso dev                  | Input tokens/mes | Output tokens/mes | Coste/mes |
| ---------------------------------- | ------------------------ | ---------------- | ----------------- | --------- |
| Claude Opus 4.7 (Planner, Judge)   | ~200 consultas profundas | ~3M (con cache)  | ~500K             | **~$150** |
| Claude Sonnet 4.6 (Makers)         | ~500 consultas           | ~8M (con cache)  | ~2M               | **~$200** |
| Claude Haiku 4.5 (auxiliares)      | ~2.000 llamadas pequeñas | ~5M              | ~500K             | **~$10**  |
| Evals nightly (Batch API, 50% dto) | ~100 casos/noche         | ~2M/mes          | ~400K/mes         | **~$30**  |

> Nota: Bedrock prompt caching reduce los costes de input significativamente
> cuando el mismo contexto RAG se reutiliza. El 90% de descuento en tokens cacheados
> se aplica al contexto de especialista que no cambia entre sesiones.

**Subtotal LLM: ~$390/mes** (estimación conservadora sin caching agresivo)

### Observabilidad

| Servicio                      | Especificación            | Coste/mes                   |
| ----------------------------- | ------------------------- | --------------------------- |
| **CloudWatch Logs**           | ~5 GB ingestados/mes      | $0.57/GB × 5 = **~$3**      |
| **CloudWatch Metrics custom** | ~50 métricas × 730 puntos | $0.30/10 métricas = **~$2** |
| **CloudWatch Alarms**         | ~20 alarmas               | $0.10/alarm = **~$2**       |
| **X-Ray**                     | ~15.000 trazas/mes        | $5/1M trazas = **~$0.10**   |
| **Langfuse ECS Fargate**      | 1 task × 0.5 vCPU × 1 GB  | ~$0.02/h × 730h = **~$15**  |
| **Grafana ECS Fargate**       | 1 task × 0.5 vCPU × 1 GB  | **~$15**                    |

**Subtotal observabilidad: ~$37/mes**

### Seguridad

| Servicio            | Especificación                                    | Coste/mes |
| ------------------- | ------------------------------------------------- | --------- |
| **GuardDuty**       | ~$0.50/GB VPC Flow Logs; ~$4/1M CloudTrail events | **~$15**  |
| **Security Hub**    | ~$0.001/finding check × 15.000 checks             | **~$15**  |
| **AWS Config**      | ~1.000 configuration items × $0.003               | **~$3**   |
| **KMS CMK**         | 2 CMKs dev × $1/mes + ~10K API calls              | **~$3**   |
| **Secrets Manager** | ~10 secrets × $0.40/secret/mes                    | **~$4**   |

**Subtotal seguridad: ~$40/mes**

---

## Resumen `workloads-dev`

| Categoría                       | Coste/mes             |
| ------------------------------- | --------------------- |
| Compute y hosting               | $273–423              |
| Datos (Aurora + S3 + SageMaker) | $196                  |
| Networking (con centralización) | $90                   |
| LLM Inference (variable)        | $390                  |
| Observabilidad                  | $37                   |
| Seguridad                       | $40                   |
| **TOTAL workloads-dev**         | **~$1.026–1.176/mes** |

---

## Cuentas auxiliares (management, log-archive, security, network)

| Cuenta               | Servicios principales                                          | Coste/mes     |
| -------------------- | -------------------------------------------------------------- | ------------- |
| `management`         | Control Tower, Organizations, IAM IC                           | ~$30          |
| `log-archive`        | S3 (CloudTrail + Flow Logs), Athena                            | ~$40          |
| `security`           | GuardDuty aggregator, Security Hub, Config aggregator          | ~$35          |
| `network`            | Transit Gateway, Route53 Resolver, VPC Endpoints centralizados | ~$80          |
| **Total auxiliares** |                                                                | **~$185/mes** |

---

## TOTAL GLOBAL Fase 9 MVP

| Componente         | Rango                 |
| ------------------ | --------------------- |
| workloads-dev      | $1.026–1.176          |
| Cuentas auxiliares | ~$185                 |
| **TOTAL**          | **~$1.200–1.360/mes** |

> **Estimación conservadora para presupuestación: $1.500/mes** (incluye margen del 10%
> para variabilidad de LLM tokens y costes no previstos).

---

## Proyección de escalado

| Fase                       | Configuración                                | Coste estimado                       |
| -------------------------- | -------------------------------------------- | ------------------------------------ |
| Fase 9 — workloads-dev     | Como arriba                                  | ~$1.200–1.500/mes                    |
| Fase 9.5 — + workloads-pre | pre ≈ dev sin spot/pause + backups completos | +~$900/mes → **~$2.100–2.400/mes**   |
| Fase 10 — + workloads-pro  | pro = 2× pre con reserved instances          | +~$1.500/mes → **~$3.600–4.000/mes** |

---

## Optimizaciones aplicables desde Fase 9

### Implementar en 9.1

| Optimización                                       | Ahorro estimado                          | Complejidad                                                       |
| -------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------- |
| **ECS Fargate Spot** para API/Web tasks            | ~30% del compute ECS = ~$30/mes          | Baja — flag en CDK                                                |
| **Aurora auto-pause** en dev fuera de horario      | ~40% del coste Aurora dev = ~$58/mes     | Baja — parámetro CDK                                              |
| **Bedrock prompt caching** agresivo (contexto RAG) | ~30% del LLM input cost = ~$60/mes       | Media — requiere `cache_control` blocks en BedrockAnthropicClient |
| **Batch API** para evals nightly                   | 50% descuento en Haiku/Sonnet = ~$20/mes | Baja — cambiar endpoint en eval runner                            |

**Ahorro total optimizaciones Fase 9: ~$168/mes** → coste real esperado: **~$1.032–1.332/mes**.

### Evaluar en Fase 10

| Optimización                                 | Ahorro estimado                  | Trigger para activar                       |
| -------------------------------------------- | -------------------------------- | ------------------------------------------ |
| **Bedrock Reserved Capacity** (Sonnet/Haiku) | ~25% del coste Sonnet = ~$50/mes | Volumen estable > 3 meses                  |
| **Compute Savings Plans** (ECS Fargate)      | ~20% compute                     | Patrón de uso estable                      |
| **S3 Intelligent-Tiering**                   | ~15% S3                          | Si >100 GB de objetos con acceso irregular |
| **VPC Endpoint centralización completa**     | ~$85/mes (de 2 cuentas a 1)      | workloads-pre activa                       |

---

## Alertas de coste (integración FinOps ADR 0029)

Umbrales configurados en AWS Budgets + alerta Grafana Tier 1 `DailyCostSpike`:

| Alerta              | Umbral                  | Acción                               |
| ------------------- | ----------------------- | ------------------------------------ |
| Monthly budget 80%  | $1.200/mes × 0.8 = $960 | Notificación warning                 |
| Monthly budget 100% | $1.500/mes              | Notificación critical                |
| Daily cost spike    | >2× media 7 días        | Notificación critical (Grafana)      |
| LLM tokens/día      | >$50/día                | Warning — revisar consultas costosas |

Las alertas se implementan en `SecurityStack` CDK (AWS Budgets) y en Grafana (ADR 0031).
