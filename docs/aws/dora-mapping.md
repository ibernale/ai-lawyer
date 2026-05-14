# DORA Compliance Mapping — lex-agents AWS (Fase 9.5)

> EU Regulation 2022/2554 (DORA) — Digital Operational Resilience Act
> Aplicable a: entidades financieras UE (uso interno banca)
> ADR de referencia: ADR 0044

## Tabla de Controles

| Artículo DORA                                         | Requisito                                            | Control AWS                                                                | Implementado | Evidencia disponible                            |
| ----------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------- | :----------: | ----------------------------------------------- |
| **Art. 5.1** Gobernanza TIC                           | Marco de gobernanza TIC documentado                  | IAM Identity Center + SCPs + Organizations                                 |   Parcial    | Configuración CDK versionada en git             |
| **Art. 6.1** Marco de gestión de riesgos TIC          | Proceso de identificación y clasificación de riesgos | AWS Config + Security Hub conformance packs                                |   Parcial    | Config compliance report diario                 |
| **Art. 8.1** Inventario de activos TIC                | Inventario actualizado de activos                    | AWS Config Resource Inventory + Resource Explorer                          |   Parcial    | Config snapshot diario                          |
| **Art. 8.2** Clasificación de información             | Clasificación según criticidad                       | S3 bucket tags + Resource tags                                             |   Parcial    | Tagging policy en SCPs                          |
| **Art. 9.2** Cifrado en tránsito                      | TLS para toda comunicación                           | ALB TLS 1.3, Secrets Manager HTTPS, VPC endpoints                          | Implementado | evidence_collector (CloudTrail API calls)       |
| **Art. 9.3** Cifrado en reposo                        | Cifrado de datos almacenados                         | KMS CMK: Aurora, S3, Secrets, EFS, EBS                                     | Implementado | evidence_collector `kms_rotation_enabled` check |
| **Art. 9.4** Gestión de claves criptográficas         | Rotación y custodia de claves                        | KMS CMK rotación anual automática                                          | Implementado | evidence_collector `kms_rotation_enabled` check |
| **Art. 9.5** MFA para acceso crítico                  | Autenticación multi-factor                           | IAM Identity Center MFA obligatorio + SCP DenyIAMConsolePasswordWithoutMFA | Implementado | Security Hub DORA-MFA-Coverage insight          |
| **Art. 9.6** Gestión de acceso con privilegios        | Principio de mínimo privilegio                       | IAM roles por servicio, sin `AdministratorAccess` en producción, SCPs      |   Parcial    | IAM Access Analyzer (planned Fase 10)           |
| **Art. 10.1** Detección de anomalías TIC              | Monitorización continua para detección de incidentes | GuardDuty + Security Hub + CloudTrail + CW Alarms                          | Implementado | evidence_collector `guardduty_enabled` check    |
| **Art. 10.2** Alertas automáticas                     | Sistema de alertas sobre amenazas                    | GuardDuty → EventBridge → SNS → Slack                                      | Implementado | Alert router Lambda activo                      |
| **Art. 11.1** Política de respuesta y recuperación    | Procedimientos documentados                          | Runbook operacional (`docs/aws/runbook.md`)                                | Implementado | Documento versionado en git                     |
| **Art. 11.2** Continuidad del negocio TIC             | Objetivos de recuperación (RTO/RPO)                  | Aurora PITR (RPO 5min), S3 CRR (RPO 15min)                                 | Implementado | AWS Backup plan diario                          |
| **Art. 11.3** Plan de respaldo y restauración         | Copias de seguridad verificadas                      | AWS Backup (Aurora diario), S3 Object Lock WORM                            | Implementado | evidence_collector `config_compliance` check    |
| **Art. 11.4** Capacidades de recuperación             | Entorno de DR preparado                              | S3 CRR a eu-west-1, DR runbook                                             |   Parcial    | S3 replication metrics                          |
| **Art. 12.1** Gestión de incidentes TIC               | Clasificación y notificación de incidentes           | CloudWatch Alarms P1/P2/P3, DORA incident runbook                          | Implementado | CloudWatch alarm state changes                  |
| **Art. 17.1** Pruebas de resiliencia                  | Testing anual de resiliencia TIC                     | E2E test suite (`tests/e2e/test_e2e_aws.py`)                               |   Parcial    | GitHub Actions workflow `e2e-aws.yml`           |
| **Art. 19.1** Notificación de incidentes mayores      | Reporte a autoridad competente en 4h                 | Proceso documentado en runbook §13                                         |   Parcial    | Formulario de notificación en runbook           |
| **Art. 28.1** Gestión de riesgos TIC de terceros      | Due diligence sobre proveedores TIC                  | ADR 0037 (Anthropic), ADR 0040 (AWS), ADR 0048 (Langfuse)                  |   Parcial    | ADRs versionados en git                         |
| **Art. 30.1** Cláusulas contractuales con proveedores | Contratos con cláusulas DORA                         | AWS DPA, Anthropic DPA                                                     |   Parcial    | Contratos fuera de este repositorio             |

## Estado de Implementación por Artículo

```
Art. 5-6   (Gobernanza)         ███░░ 60%  — IAM+SCPs completo, riesgos documentación parcial
Art. 8     (Activos)            ████░ 80%  — Config inventory activo
Art. 9     (Protección)         █████ 95%  — KMS+TLS+MFA implementado
Art. 10    (Detección)          █████ 90%  — GuardDuty+CW activo
Art. 11    (Respuesta/Recovery) ████░ 80%  — PITR+CRR+Backup activo, DR parcial
Art. 12    (Incidentes)         ████░ 75%  — Clasificación+alarms activo, notificación manual
Art. 17    (Testing)            ███░░ 60%  — E2E tests, TLPT pendiente Fase 10
Art. 19    (Reporting)          ██░░░ 40%  — Proceso documentado, herramienta manual
Art. 28-30 (Terceros)           ███░░ 55%  — ADRs completos, contratos externos
```

## Evidencias Generadas por evidence_collector

El Lambda `evidence_collector` (ComplianceStack) genera evidencias diarias en:
`s3://lex-agents-dev-compliance-docs-ACCOUNT/evidence/YYYY-MM-DD/`

| Fichero                     | Control                               | Artículo DORA      |
| --------------------------- | ------------------------------------- | ------------------ |
| `kms_rotation_enabled.json` | Rotación anual de CMKs activas        | Art. 9.4           |
| `cloudtrail_enabled.json`   | Trail multi-región activo y validado  | Art. 10.1          |
| `guardduty_enabled.json`    | Detector activo, 0 findings HIGH      | Art. 10.1          |
| `config_compliance.json`    | Config recorder activo, >= 80% reglas | Art. 8.1, Art. 6.1 |

Reporte consolidado en: `reports/YYYY-MM-DD/summary.md`

## Gaps y Plan de Cierre

| Gap                                       | Artículo | Plan                               | Fase    |
| ----------------------------------------- | -------- | ---------------------------------- | ------- |
| TLPT (prueba de penetración con amenazas) | Art. 26  | Contratar red team externo         | Fase 11 |
| Registro de proveedores TIC críticos      | Art. 28  | Completar registro DORA            | Fase 10 |
| IAM Access Analyzer habilitado            | Art. 9.6 | Añadir a SecurityBaselineStack     | Fase 10 |
| Notificación automatizada Art. 19         | Art. 19  | Integración con portal regulatorio | Fase 12 |
| DR test documentado y ejecutado           | Art. 17  | Ejercicio DR trimestral            | Fase 10 |
| CloudFront WAF                            | Art. 9.2 | Añadir WAF a ALB/CF                | Fase 10 |
