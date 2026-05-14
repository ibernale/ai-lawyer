# Runbook Operacional — lex-agents AWS (Fase 9)

> Documento de referencia operacional para el equipo de plataforma.
> Actualizar tras cada cambio de arquitectura relevante.
> Version: Fase 9.5 | Idioma: Español (doc jurídico interno)

---

## 1. Pre-requisitos y Acceso

### Herramientas requeridas
- AWS CLI v2 (`aws --version`)
- CDK v2 (`npx cdk --version`)
- Node.js 20 LTS
- Python 3.12
- `jq`, `curl`

### Configuración de credenciales
```bash
# Via SSO (IAM Identity Center — recomendado)
aws configure sso
aws sso login --profile lex-agents-dev

# Verificar identidad activa
aws sts get-caller-identity --profile lex-agents-dev
```

### Cuentas AWS
| Cuenta | Alias | Uso |
|--------|-------|-----|
| `111...` | management | Organizations, Identity Center, SCPs |
| `222...` | log-archive | CloudTrail, Flow Logs (WORM 7y) |
| `333...` | security | GuardDuty, Security Hub, Audit Manager |
| `444...` | network | Transit Gateway |
| `555...` | workloads-dev | Aplicación principal |
| `TBD` | workloads-pre | Pre-producción (Fase 9.5) |

---

## 2. Despliegue y Rollback

### Despliegue completo desde cero
```bash
cd infra/cdk
cp cdk.context.json.example cdk.context.json
# Editar cdk.context.json con los IDs reales de las cuentas

# Bootstrap cada cuenta (solo la primera vez)
npx cdk bootstrap aws://111.../eu-west-1 --profile lex-agents-management
npx cdk bootstrap aws://555.../eu-west-1 --profile lex-agents-dev

# Sintetizar y desplegar todo
npx cdk synth --all
npx cdk deploy --all --require-approval never
```

### Despliegue incremental
```bash
cd infra/cdk
npx cdk diff LexAgents-Dev-App          # Ver cambios antes de aplicar
npx cdk deploy LexAgents-Dev-App --require-approval never
```

### Rollback de una stack
```bash
# Opción 1: Revertir al commit anterior en git y re-desplegar
git revert HEAD
npx cdk deploy LexAgents-Dev-App

# Opción 2: CloudFormation rollback manual
aws cloudformation cancel-update-stack \
  --stack-name LexAgents-Dev-App \
  --profile lex-agents-dev

# Opción 3: ECS rolling update al tag anterior
aws ecs update-service \
  --cluster lex-agents-dev \
  --service lex-agents-dev-api \
  --task-definition lex-agents-dev-api:PREVIOUS_REVISION \
  --region eu-west-1
```

---

## 3. Escalado Manual

### Escalar servicio ECS API
```bash
aws ecs update-service \
  --cluster lex-agents-dev \
  --service lex-agents-dev-api \
  --desired-count 3 \
  --region eu-west-1

# Verificar
aws ecs describe-services \
  --cluster lex-agents-dev \
  --services lex-agents-dev-api \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'
```

### Escalar Aurora Serverless v2
```bash
# Verificar capacidad actual
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name ServerlessDatabaseCapacity \
  --dimensions Name=DBClusterIdentifier,Value=lex-agents-dev \
  --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 --statistics Maximum

# Aumentar maxCapacity si es necesario (via CDK/CFN — no directamente)
# Editar serverlessV2MaxCapacity en data.ts y re-desplegar DataStack
```

---

## 4. Rotación de Credenciales

### Rotar clave API de Anthropic
```bash
# 1. Generar nueva clave en console.anthropic.com
# 2. Actualizar en Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id /lex-agents/dev/anthropic/api-key \
  --secret-string '{"value":"sk-ant-NEW_KEY"}' \
  --profile lex-agents-dev

# 3. Forzar rolling update de ECS para cargar nuevo secreto
aws ecs update-service \
  --cluster lex-agents-dev \
  --service lex-agents-dev-api \
  --force-new-deployment \
  --region eu-west-1
```

### Rotar secreto de base de datos (app-user)
```bash
# La rotación automática está configurada cada 30 días (ADR 0050).
# Para rotación manual:
aws secretsmanager rotate-secret \
  --secret-id /lex-agents/dev/db/app-user \
  --profile lex-agents-dev

# Verificar que la rotación completó
aws secretsmanager describe-secret \
  --secret-id /lex-agents/dev/db/app-user \
  --query 'LastRotatedDate'
```

### Rotar claves KMS
Las CMKs tienen rotación automática anual activada. Para forzar rotación:
```bash
aws kms enable-key-rotation \
  --key-id alias/lex-agents-dev-rds \
  --profile lex-agents-dev
```

---

## 5. Backup y Restore Aurora

### Verificar estado de backups
```bash
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier lex-agents-dev \
  --snapshot-type automated \
  --query 'DBClusterSnapshots[0:3].{ID:DBClusterSnapshotIdentifier,Created:SnapshotCreateTime,Status:Status}'
```

### Restore a un punto en el tiempo (PITR)
```bash
# Restaurar a las 14:00 UTC del día anterior
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier lex-agents-dev \
  --db-cluster-identifier lex-agents-dev-restore-20260514 \
  --restore-to-time 2026-05-13T14:00:00Z \
  --engine-mode provisioned \
  --vpc-security-group-ids sg-XXXXX \
  --db-subnet-group-name lex-agents-dev-aurora-subnet-group

# NOTA: el cluster restaurado necesita un nuevo writer instance
aws rds create-db-instance \
  --db-instance-identifier lex-agents-dev-restore-writer \
  --db-cluster-identifier lex-agents-dev-restore-20260514 \
  --db-instance-class db.serverless \
  --engine aurora-postgresql
```

---

## 6. Disaster Recovery (DR)

### Escenario: fallo de región eu-west-1
Los datos están replicados a eu-west-1 (DR) vía CRR (raw, canonical, backups).
Para activar DR:
1. Verificar buckets DR: `lex-agents-raw-dev-dr`, `lex-agents-canonical-dev-dr`, `lex-agents-backups-dev-dr`
2. Hacer bootstrap CDK en eu-west-1 DR
3. Desplegar DataDrStack (pendiente — ver `docs/aws/dr-plan.md`)
4. Actualizar DNS para apuntar al nuevo ALB en DR

### RTO/RPO targets
| Componente | RPO | RTO |
|-----------|-----|-----|
| Base de datos (PITR) | 5 min | 30 min |
| S3 documentos (CRR) | 15 min | 5 min |
| CloudTrail logs | 7 días | N/A (solo lectura) |

---

## 7. Gestión de Kill Switches

### Listar kill switches activos
```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://API_BASE_URL/api/v1/admin/kill_switches
```

### Activar kill switch de emergencia
```bash
# Ejemplo: desactivar ingest pipeline
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"switch": "ingest_pipeline", "enabled": false, "reason": "Formato BOE cambiado"}' \
  https://API_BASE_URL/api/v1/admin/kill_switches
```

### Monitorizar estado en CloudWatch
Los kill switches publican métricas en `LexAgents/KillSwitch`. Ver dashboard `lex-agents-dev`.

---

## 8. Investigar Query Lenta

### Paso 1: Identificar en Aurora slow query log
```bash
# Ver últimas 100 queries lentas (> 5s)
aws logs filter-log-events \
  --log-group-name /lex-agents/dev/aurora \
  --filter-pattern '"duration: [0-9][0-9][0-9][0-9]"' \
  --start-time $(date -u -v-1H +%s000) \
  | jq '.events[].message'
```

### Paso 2: Correlacionar con trace de Langfuse
```bash
curl -u "$LANGFUSE_PK:$LANGFUSE_SK" \
  "$LANGFUSE_HOST/api/public/traces?limit=5&orderBy=latency&order=DESC"
```

### Paso 3: Revisar plan de ejecución
```sql
-- Conectar via SSM Session Manager port-forward
EXPLAIN ANALYZE
SELECT * FROM audit_logs WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC LIMIT 100;
```

### Paso 4: Verificar índices
```sql
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY idx_tup_read DESC;
```

---

## 9. Investigar Coste Anómalo

### Paso 1: Revisar alarma de Cost Anomaly Detection
La alarma `lex-agents-dev-anomaly-alerts` se dispara cuando el gasto diario supera el umbral.

```bash
aws ce get-anomalies \
  --date-interval StartDate=2026-05-01,EndDate=2026-05-14 \
  --total-impact-filter '{"NumericOperator":"GREATER_THAN","StartValue":10}'
```

### Paso 2: Dashboard FinOps
Ver dashboard `lex-agents-dev-finops` en CloudWatch para tendencia de 30 días.

### Paso 3: Desglose por servicio
```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-05-01,End=2026-05-14 \
  --granularity DAILY \
  --metrics "BlendedCost" \
  --group-by Type=DIMENSION,Key=SERVICE \
  | jq '.ResultsByTime[-1].Groups | sort_by(.Metrics.BlendedCost.Amount | tonumber) | reverse | .[0:5]'
```

### Paso 4: Acciones comunes
- ECS alto: verificar despliegues incorrectos con tasks zombie
- S3 alto: verificar request rates (posible loop de reintentos)
- NAT Gateway alto: verificar tráfico de salida (¿nuevo endpoint externo?)
- RDS alto: verificar Aurora ACU máximo (`auroraCapacityHigh` alarm)

---

## 10. Investigar Alerta GuardDuty

### Triaje inicial
```bash
# Listar findings activos HIGH/CRITICAL
aws guardduty list-findings \
  --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text) \
  --finding-criteria '{"Criterion":{"severity":{"Gte":7},"service.archived":{"Eq":["false"]}}}' \
  --profile lex-agents-security

# Ver detalles del finding
aws guardduty get-findings \
  --detector-id DETECTOR_ID \
  --finding-ids FINDING_ID \
  --profile lex-agents-security
```

### Tipos de findings y respuesta
| Finding | Respuesta inicial |
|---------|------------------|
| `UnauthorizedAccess:IAMUser/MaliciousIPCaller` | Revocar credenciales, revisar CloudTrail |
| `CryptoCurrency:EC2/BitcoinTool.B` | Aislar instancia, revisar Security Groups |
| `Trojan:EC2/DNSDataExfiltration` | Aislar tarea ECS, análisis forense |
| `Recon:IAMUser/UserPermissions` | Revisar accesos IAM Identity Center |

### Proceso de incidente DORA (P1)
Ver sección 13.

---

## 11. Onboarding Nuevo Admin

1. Crear usuario en IAM Identity Center (consola Management account)
2. Asignar al grupo `lex-agents-admins` en Identity Center
3. El usuario recibe permiso set `AdministratorAccess` en workloads-dev
4. Configurar MFA obligatorio (política Identity Center lo aplica)
5. Verificar acceso:
```bash
aws sso login --profile lex-agents-dev
aws sts get-caller-identity
```
6. Entregar este runbook y `docs/aws/security-controls.md`
7. Añadir al canal Slack `#lex-agents-ops`

---

## 12. Onboarding Nuevo Developer

1. Crear usuario en IAM Identity Center
2. Asignar al grupo `lex-agents-developers` (permiso set `ReadOnlyAccess` + ECR push)
3. Configurar MFA
4. Acceso a repositorio GitHub con permisos `write`
5. Verificar que GitHub Actions OIDC funciona:
   - Fork → PR → CI verde
6. Proporcionar acceso a Langfuse UI (link interno en descripción de canal)
7. Documentación de onboarding: `docs/dev-setup.md`

---

## 13. Procedimiento de Incidente DORA

### Clasificación
| Nivel | Descripción | Tiempo de respuesta | Tiempo de resolución |
|-------|-------------|--------------------|--------------------|
| P1 | Indisponibilidad total del servicio | 15 min | 4h |
| P2 | Degradación severa (> 50% errores) | 30 min | 8h |
| P3 | Degradación menor o security advisory | 2h | 24h |

### Proceso P1
1. **Detección**: Alarma CloudWatch o alerta GuardDuty → Slack `#lex-agents-incidents`
2. **Triaje** (15 min): Identificar componente afectado (ALB, ECS, Aurora, DNS)
3. **Comunicación**: Notificar a responsable DORA (CISO / responsable de riesgos TIC)
4. **Mitigación**: Ver sección correspondiente (ej. §3 escalado, §6 DR)
5. **Resolución**: Verificar métricas normales en dashboard
6. **Post-mortem**: Completar formulario DORA dentro de 4h (Art. 19 DORA)
7. **Evidencia**: El Lambda `evidence_collector` genera reporte diario automático

### Plantilla de notificación DORA Art. 19
```
Incidente Mayor TIC — NOTIFICACIÓN INICIAL
Fecha/Hora: [TIMESTAMP UTC]
Sistema afectado: lex-agents ([dev/pre/pro])
Descripción: [DESCRIPCIÓN BREVE]
Impacto: [USUARIOS AFECTADOS / DATOS COMPROMETIDOS]
Medidas adoptadas: [ACCIONES TOMADAS]
Estado: [EN RESOLUCIÓN / RESUELTO]
Próxima actualización: [TIMESTAMP]
```

---

## 14. Gestión de Pipelines de Ingest

### Ver estado de ejecuciones
```bash
# Últimas 10 ejecuciones del pipeline BOE
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:eu-west-1:555...:stateMachine:lex-agents-dev-ingest-boe \
  --max-results 10 \
  | jq '.executions[].{name,status,startDate}'
```

### Reiniciar pipeline fallido
```bash
# Obtener ARN de ejecución fallida
EXEC_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn STATE_MACHINE_ARN \
  --status-filter FAILED \
  --max-results 1 \
  --query 'executions[0].executionArn' --output text)

# Ver causa del fallo
aws stepfunctions describe-execution --execution-arn $EXEC_ARN \
  | jq '.cause'

# Re-ejecutar con los mismos parámetros
aws stepfunctions start-execution \
  --state-machine-arn STATE_MACHINE_ARN \
  --input '{"source":"boe","date":"2026-05-14"}'
```

### Silenciar alerta de formato cambiado
```bash
# Si el cambio de formato es esperado (nueva versión del BOE)
aws cloudwatch set-alarm-state \
  --alarm-name lex-agents-dev-pipeline-execution-failed \
  --state-value OK \
  --state-reason "Formato cambiado conocido — pipeline actualizado"
```

---

## 15. Gestión de Langfuse Traces

### Acceso a Langfuse UI
```bash
# Port-forward via SSM (ALB interno en VPC)
aws ssm start-session \
  --target ecs:lex-agents-dev_TASK_ID_CONTAINER \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["LANGFUSE_ALB_DNS"],"portNumber":["3000"],"localPortNumber":["3000"]}'
# Abrir http://localhost:3000 en navegador
```

### Buscar trace de una consulta específica
```bash
curl -u "$LANGFUSE_PK:$LANGFUSE_SK" \
  "$LANGFUSE_HOST/api/public/traces?tags=query_id:QUERY_ID"
```

### Limpiar traces de pruebas
```bash
# Eliminar traces del usuario de test e2e (script manual)
curl -X DELETE -u "$LANGFUSE_PK:$LANGFUSE_SK" \
  "$LANGFUSE_HOST/api/public/projects/PROJECT_ID/traces?userId=e2e-test"
```

---

## 16. Evidencias DORA (evidence_collector)

### Verificar última ejecución
```bash
aws logs tail /lex-agents/dev/evidence-collector \
  --since 24h \
  | grep "evidence_collector.done"
```

### Ver reporte diario
```bash
TODAY=$(date +%Y-%m-%d)
aws s3 cp \
  s3://lex-agents-dev-compliance-docs-ACCOUNT_ID/reports/$TODAY/summary.md \
  - | cat
```

### Ejecutar evidencia manualmente
```bash
aws lambda invoke \
  --function-name lex-agents-dev-evidence-collector \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/evidence-output.json
cat /tmp/evidence-output.json
```

### Score mínimo aceptable
El alarm `lex-agents-dev-compliance-score-low` se dispara si el score baja de 90%.
Los controles auditados son:
1. KMS key rotation (todas las CMKs activas)
2. CloudTrail multi-región activo con validación de ficheros
3. GuardDuty habilitado sin findings HIGH/CRITICAL
4. AWS Config recorder activo y >= 80% reglas compliant
