# ADR 0044 — DORA: Mapping de controles AWS

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0036 (regiones), 0037 (multi-account), 0041 (networking),
0042 (persistencia), 0043 (CDK)  
**Sub-fases afectadas:** 9.1 – 9.5  
**Marco normativo:** Reglamento (UE) 2022/2554 (DORA), aplicable desde 17 enero 2025

---

## Contexto

DORA (Digital Operational Resilience Act) impone requisitos de resiliencia operativa
digital a las entidades financieras de la UE. Santander, como entidad de crédito
sujeta a DORA, debe acreditar el cumplimiento de los artículos relevantes para los
sistemas ICT de soporte a la actividad bancaria, incluido lex-agents.

Este ADR documenta cómo los servicios AWS adoptados en las ADRs 0036–0043 satisfacen
los artículos DORA aplicables, con responsable, evidencia prevista y estado.

---

## Artículos DORA aplicables y controles AWS

### Artículo 8 — Marco de gestión del riesgo ICT

| Requisito                                | Control AWS implementado                                                                                    | Responsable            | Evidencia prevista                             | Estado   |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------- | ---------------------------------------------- | -------- |
| 8.1 Inventario de activos ICT            | AWS Config + Resource Explorer. Tags obligatorios via SCP.                                                  | Santander (gobernanza) | Config conformance pack report                 | Fase 9.1 |
| 8.2 Clasificación activos por criticidad | Tagging policy obligatoria (SCP `RequireTags`): `Environment`, `DataClassification`, `Owner`, `CostCenter`. | Santander              | Config rule `required-tags` violations = 0     | Fase 9.1 |
| 8.3 Evaluación de riesgos ICT            | AWS Trusted Advisor + Security Hub findings. Revisión mensual por responsable de plataforma.                | Santander              | Security Hub summary report mensual            | Fase 9.2 |
| 8.4 Gestión de cambios                   | CDK en Git + pull requests + aprobación manual en pre/pro. CloudTrail de cambios CloudFormation.            | Santander              | CloudTrail `CloudFormation:UpdateStack` events | Fase 9.1 |

### Artículo 9 — Protección y prevención

| Requisito                              | Control AWS implementado                                                                                                      | Responsable                       | Evidencia prevista                                                                                                    | Estado   |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------- |
| 9.2 MFA obligatorio                    | IAM Identity Center con MFA hardware obligatorio. SCP `DenyConsoleWithoutMFA`.                                                | Santander                         | CloudTrail `ConsoleLogin` events sin MFA = 0                                                                          | Fase 9.1 |
| 9.2 Acceso mínimo privilegio           | IAM Identity Center Permission Sets por rol. Security Groups por principio de mínimo privilegio (ADR 0041).                   | Santander                         | Config rule `iam-user-no-policies-check`, SG compliance                                                               | Fase 9.1 |
| 9.3 Cifrado en reposo                  | KMS Customer Managed Keys. Aurora SSE-KMS. S3 SSE-KMS. Secrets Manager KMS.                                                   | AWS (motor KMS) + Santander (CMK) | Config rule `encrypted-volumes`, `rds-storage-encrypted`, `s3-bucket-server-side-encryption-enabled`                  | Fase 9.1 |
| 9.3 Cifrado en tránsito                | TLS 1.2+ en ALB. TLS en Aurora (`require_secure_transport`). HTTPS-only en VPC Endpoints.                                     | Santander                         | ALB access logs (protocol TLSv1.2/1.3); `rds-ssl-required` Config rule                                                | Fase 9.1 |
| 9.4 Segmentación de red                | VPC con 3 capas de subnets. Security Groups de mínimo privilegio. NACLs. Sin acceso público a datos.                          | Santander                         | Config rule `vpc-flow-logs-enabled`, SG compliance report                                                             | Fase 9.1 |
| 9.5 Gestión de secretos y credenciales | Secrets Manager para TODAS las credenciales. Sin API keys en variables de entorno. Rotación automática Aurora password (30d). | Santander                         | Config rule `secretsmanager-rotation-enabled-check`. Auditoría manual de ECS task defs sin credenciales en plaintext. | Fase 9.1 |
| 9.6 Gestión de accesos privilegiados   | SSM Session Manager para acceso a containers (no SSH). CloudTrail de sesiones SSM. Sin bastion hosts.                         | Santander                         | CloudTrail `ssm:StartSession` events                                                                                  | Fase 9.1 |

### Artículo 10 — Detección

| Requisito                        | Control AWS implementado                                                                                                        | Responsable                                  | Evidencia prevista                                                                                   | Estado   |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------- |
| 10.1 Detección de incidentes ICT | GuardDuty (threat detection ML). Security Hub (aggregador findings). CloudWatch Alarms → SNS → Incident Manager.                | AWS (motor GuardDuty) + Santander (response) | GuardDuty findings dashboard. Security Hub compliance score > 80%.                                   | Fase 9.1 |
| 10.2 Logging centralizado        | CloudTrail organization-wide → log-archive S3 Object Lock (WORM). Retención 7 años (DORA mínimo).                               | Santander                                    | CloudTrail integrity verification. Log count diario en log-archive S3 ≥ expected.                    | Fase 9.1 |
| 10.3 Logging de red              | VPC Flow Logs en todas las VPCs → log-archive. Athena para queries ad-hoc.                                                      | Santander                                    | Athena query sobre Flow Logs para incidentes. Flow Logs habilitados en todas las VPCs (Config rule). | Fase 9.1 |
| 10.4 Anomaly detection           | CloudWatch Logs Insights con alertas sobre patrones de error. Grafana alertas Tier 1/2 (ADR 0031). GuardDuty Anomaly detection. | Santander                                    | Alertas activas en Grafana. GuardDuty findings history.                                              | Fase 9.2 |

### Artículo 11 — Respuesta y recuperación

| Requisito                            | Control AWS implementado                                                                                                                     | Responsable                               | Evidencia prevista                                                  | Estado   |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------- | -------- |
| 11.1 Plan de continuidad ICT         | Runbook completo en `docs/runbook.md`. Arquitectura multi-AZ activa-activa en eu-central-1. Backup DR en eu-west-1.                          | Santander                                 | Runbook actualizado. DR drill semestral documentado.                | Fase 9.2 |
| 11.2 Capacidades de backup y restore | AWS Backup con políticas cross-region (eu-central-1 → eu-west-1). Aurora PITR 35 días en pre. S3 Object Lock para backups críticos (7 años). | AWS (motor backup) + Santander (política) | Backup jobs report semanal. PITR test trimestral (doc. en runbook). | Fase 9.1 |
| 11.3 RTO y RPO documentados          | RTO ≤ 4h (recovery desde backup eu-west-1). RPO ≤ 1h (Aurora PITR granularidad 5 min). Documentados en `docs/runbook.md`.                    | Santander                                 | DR drill con medición de RTO real.                                  | Fase 9.5 |
| 11.5 Comunicación de incidentes      | AWS Incident Manager para P1/P2. Runbook sección "Emergencias" (docs/incident-response.md).                                                  | Santander                                 | Incident Manager runbooks configurados.                             | Fase 9.2 |

### Artículos 17–20 — Gestión, clasificación y notificación de incidentes ICT

| Requisito                    | Control AWS implementado                                                                                                                 | Responsable | Evidencia prevista                                                          | Estado   |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------- | --------------------------------------------------------------------------- | -------- |
| 17 Clasificación incidentes  | AWS Incident Manager con severity tiers. CloudWatch Alarm severity: Critical (P1), High (P2), Medium (P3).                               | Santander   | Incident Manager playbooks con criterios de clasificación alineados a DORA. | Fase 9.2 |
| 19 Notificación inicial (4h) | Alerta Critical → SNS → email/Slack en ≤5 min. AWS Incident Manager timeline para acreditar tiempos. Template de notificación a BdE/BCE. | Santander   | Incident Manager timeline exports. Template BdE notificación.               | Fase 9.2 |
| 20 Informe final incidente   | Template de incident report en `docs/incident-response.md` con secciones requeridas por RTS DORA.                                        | Santander   | Incident reports archivados en S3 log-archive con retención 7 años.         | Fase 9.2 |

### Artículos 28–30 — Gestión del riesgo de terceros ICT

| Requisito                      | Control AWS implementado                                                                                                      | Responsable     | Evidencia prevista                                | Estado   |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | --------------- | ------------------------------------------------- | -------- |
| 28 Evaluación proveedores ICT  | AWS es proveedor ICT crítico de tercer nivel. Due diligence: AWS SOC 2 Type II, ISO 27001, PCI DSS. Contrato AWS DPA firmado. | Santander Legal | AWS Artifact: SOC 2 report, ISO cert. DPA signed. | Fase 9.0 |
| 28.7 Concentración de riesgo   | Dependencia primaria: AWS (infra) + Anthropic/Bedrock (LLM). Documentada. Exit strategy < 48h documentada abajo.              | Santander       | Exit strategy en este ADR.                        | Fase 9.0 |
| 29 Acuerdos contractuales      | Contrato AWS Enterprise con SLA. Standard Contractual Clauses para transferencias de datos EEA.                               | Santander Legal | Contrato firmado archivado. SCC firmadas.         | Fase 9.0 |
| 30 Registro de proveedores ICT | Registro formal de proveedores ICT críticos (AWS, Anthropic). Revisión anual.                                                 | Santander Risk  | Registro en sistema GRC Santander.                | Fase 9.1 |

### Artículo 26 — TLPT (Threat-Led Penetration Testing)

| Requisito                           | Aplicabilidad                                                                                                             | Decisión                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 26 Pruebas de penetración avanzadas | **No aplicable en Fase 9** (MVP sin workload productivo). TLPT aplica a sistemas en producción con volumen significativo. | Pre-requisito documentado para Fase 10 antes de activar `workloads-pro`. |

---

## Exit Strategy: AgentCore + Bedrock → Stack independiente

En caso de incidente mayor AWS, fallo catastrófico de Bedrock en eu-central-1, o decisión
regulatoria de cambio de proveedor, el proceso de migración de vuelta al stack independiente
es:

**Tiempo estimado de recuperación: < 48 horas**

```
Hora 0:   Activar KILL_SWITCH global (POST /api/v1/admin/system/kill/global)
Hora 1:   Provisionar ECS Fargate standalone para OrchestratorV2 en eu-west-1
Hora 2:   Cambiar LLM_PROVIDER=anthropic, apuntar ANTHROPIC_API_KEY desde Secrets Manager
Hora 3:   Restaurar Qdrant desde último export JSONL en S3 backup (eu-west-1)
Hora 6:   Smoke tests contra stack independiente
Hora 24:  Cutover DNS (Route53 failover policy)
Hora 48:  Monitoreo estabilizado; KILL_SWITCH liberado
```

**Componentes que NO cambian en el exit:**

- `packages/agents/` — código del agente, sin cambios.
- `packages/rag/HybridRetriever` — se reconecta a Qdrant (mismo interfaz).
- `packages/shared/AnthropicClientWrapper` — ya existe, solo activar `LLM_PROVIDER=anthropic`.
- `packages/audit/`, `packages/admin/` — pueden operar con SQLite en emergencia o Aurora eu-west-1.

**Componentes que sí requieren trabajo:**

- `packages/memory/` — reimplementar AgentCore Memory como SQLite local (1-2 días).
- `packages/ingest/` — reconectar Custom Chunking Lambda a Qdrant indexer (1 día).

**Registro de concentración de riesgo:**
Esta exit strategy se archiva en el sistema GRC de Santander como evidencia del análisis
de concentración de riesgo exigido por DORA art. 28.7. Se revisa anualmente.

---

## Consecuencias

- Cada sub-fase 9.x verifica que los controles aquí documentados están implementados
  antes de pasar a la siguiente.
- El CDK `SecurityStack` provee GuardDuty, Config rules y Backup automáticamente.
- `docs/runbook.md` se actualiza en Fase 9.2 con los procedimientos de respuesta e
  incidente específicos del entorno AWS.
- El registro de proveedores ICT se actualiza en el GRC de Santander antes de activar
  cualquier workload en `workloads-dev`.
