# Plan de Recuperación ante Desastres (DR) — lex-agents

**Referencia:** ADR 0051 — Backup-Restore a eu-west-1  
**Versión:** 1.0  
**Última revisión:** 2026-05-14  
**Propietario:** Ignacio Bernal (Santander)  
**Revisión técnica:** Requerida antes de primer test DR real

---

## 1. Criterios de activación del DR

El procedimiento de DR se activa cuando concurren **todos** los criterios siguientes:

| Criterio                        | Descripción                                                            |
| ------------------------------- | ---------------------------------------------------------------------- |
| **Región primaria inaccesible** | eu-central-1 no responde a peticiones durante > 30 minutos             |
| **Impacto confirmado en datos** | Aurora o S3 no disponibles (no solo latencia elevada)                  |
| **Decisión escalada**           | Responsable de plataforma + responsable de negocio aprueban activación |
| **SLA incumplido o en riesgo**  | RTO dev: 8h / RTO staging: 4h / RTO prod: 2h                           |

**No activar DR por:**

- Latencia elevada transitoria (< 30 min)
- Degradación parcial de un servicio individual (escalar dentro de la región primaria)
- Fallo de una única AZ (Aurora Serverless v2 es multi-AZ por diseño)

**Contacto de decisión:** Ver Sección 8.

---

## 2. Inventario de activos con RPO/RTO

| Activo                                    | Región primaria | Región DR | RPO dev | RTO dev | Mecanismo                     |
| ----------------------------------------- | --------------- | --------- | ------- | ------- | ----------------------------- |
| Aurora PostgreSQL (`lex-agents-dev`)      | eu-central-1    | eu-west-1 | 24h     | 8h      | AWS Backup daily snapshot     |
| Aurora Langfuse (`langfuse-dev`)          | eu-central-1    | eu-west-1 | 24h     | 8h      | AWS Backup daily snapshot     |
| S3 raw (`lex-agents-raw-dev`)             | eu-central-1    | eu-west-1 | ~15min  | —       | S3 CRR continuo               |
| S3 canonical (`lex-agents-canonical-dev`) | eu-central-1    | eu-west-1 | ~15min  | —       | S3 CRR continuo               |
| S3 backups (`lex-agents-backups-dev`)     | eu-central-1    | eu-west-1 | ~15min  | —       | S3 CRR continuo               |
| Código de aplicación                      | GitHub          | GitHub    | 0       | 30min   | Redesplegar desde rama `main` |
| Infraestructura CDK                       | GitHub          | GitHub    | 0       | 30min   | `cdk deploy` en cuenta DR     |

> **Nota:** S3 evals está excluido del CRR. Los datos de evaluación son reproducibles mediante re-ingestión.

---

## 3. Procedimiento de restore Aurora

### 3.1 Prerrequisitos

```bash
# Verificar que el vault DR existe en eu-west-1
aws backup list-backup-vaults --region eu-west-1 \
  --query "BackupVaultList[?BackupVaultName=='lex-agents-dev-dr']"

# Si no existe, bootstrapearlo ANTES del primer backup:
aws backup create-backup-vault \
  --backup-vault-name lex-agents-dev-dr \
  --region eu-west-1
```

### 3.2 Identificar el punto de restauración más reciente

```bash
# Listar recovery points disponibles en eu-west-1
aws backup list-recovery-points-by-backup-vault \
  --backup-vault-name lex-agents-dev-dr \
  --region eu-west-1 \
  --query "RecoveryPoints[?ResourceType=='RDS'].{ARN:RecoveryPointArn,Status:Status,Completed:CompletionDate}" \
  --output table
```

### 3.3 Restaurar el cluster Aurora desde snapshot

```bash
# Variables
RECOVERY_POINT_ARN="arn:aws:backup:eu-west-1:123456789012:recovery-point:XXXX"
DB_CLUSTER_ID="lex-agents-dev-restored"
SUBNET_GROUP="lex-agents-dev-subnet-group"  # crear previamente si no existe
VPC_SG_ID="sg-XXXX"  # SG del cluster Aurora en eu-west-1

# Iniciar restauración
aws backup start-restore-job \
  --recovery-point-arn "$RECOVERY_POINT_ARN" \
  --iam-role-arn "arn:aws:iam::123456789012:role/AWSBackupDefaultServiceRole" \
  --resource-type "RDS" \
  --metadata \
    DBClusterIdentifier="$DB_CLUSTER_ID",\
    Engine=aurora-postgresql,\
    EngineVersion=16.4,\
    DBSubnetGroupName="$SUBNET_GROUP",\
    VpcSecurityGroupIds="$VPC_SG_ID" \
  --region eu-west-1

# Monitorizar progreso del restore job
aws backup describe-restore-job \
  --restore-job-id <restore-job-id> \
  --region eu-west-1 \
  --query "{Status:Status,Created:CreationDate,Completed:CompletionDate}"
```

### 3.4 Verificar conectividad Aurora restaurada

```bash
# Una vez el cluster esté AVAILABLE:
aws rds describe-db-clusters \
  --db-cluster-identifier "$DB_CLUSTER_ID" \
  --region eu-west-1 \
  --query "DBClusters[0].{Status:Status,Endpoint:Endpoint,Port:Port}"

# Test de conexión (desde máquina con acceso al VPC DR):
psql "host=<endpoint> port=5432 dbname=lex_agents user=postgres sslmode=require"
```

---

## 4. Verificación de replicación S3

```bash
DR_REGION="eu-west-1"

# Verificar que los objetos críticos han sido replicados
for bucket in raw canonical backups; do
  echo "=== Verificando lex-agents-${bucket}-dev-dr ==="
  aws s3 ls "s3://lex-agents-${bucket}-dev-dr" \
    --region "$DR_REGION" \
    --summarize \
    --human-readable | tail -2
done

# Comparar número de objetos entre origen y réplica (para un prefijo de muestra)
# Origen (eu-central-1):
aws s3api list-objects-v2 \
  --bucket "lex-agents-raw-dev-<account>" \
  --region eu-central-1 \
  --query "length(Contents)"

# DR (eu-west-1):
aws s3api list-objects-v2 \
  --bucket "lex-agents-raw-dev-dr" \
  --region eu-west-1 \
  --query "length(Contents)"
```

> **Nota sobre RPO:** El CRR de S3 tiene SLA de 99.99% dentro de 15 minutos para objetos estándar. Si se requiere garantía de tiempo de replicación menor, habilitar S3 Replication Time Control (RTC) — coste adicional ~$0.015/GB replicado.

---

## 5. Cutover DNS / ALB

### 5.1 Route 53 (si se ha configurado Hosted Zone)

```bash
# Obtener el DNS del ALB en la región DR
DR_ALB_DNS=$(aws elbv2 describe-load-balancers \
  --names "lex-agents-dev" \
  --region eu-west-1 \
  --query "LoadBalancers[0].DNSName" \
  --output text)

# Actualizar registro CNAME / Alias en Route 53
# (ajustar HostedZoneId y RecordName según configuración real)
aws route53 change-resource-record-sets \
  --hosted-zone-id "ZXXXXXXXXXXXXX" \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.lex-agents.internal",
        "Type": "CNAME",
        "TTL": 60,
        "ResourceRecords": [{"Value": "'"$DR_ALB_DNS"'"}]
      }
    }]
  }'
```

### 5.2 Sin Route 53 (acceso directo por DNS del ALB)

Comunicar a los consumidores internos el nuevo endpoint del ALB en eu-west-1.  
Actualizar variables de entorno de los clientes que usen `API_BASE_URL` directamente.

### 5.3 Verificar propagación DNS

```bash
# Desde varios clientes internos:
dig api.lex-agents.internal +short

# Verificar que responde el ALB de DR:
curl -f "http://$DR_ALB_DNS/health" -H "Host: api.lex-agents.internal"
```

---

## 6. Smoke test checklist post-restore

Ejecutar en orden. Cada comprobación debe devolver resultado exitoso antes de continuar.

- [ ] **Aurora disponible:** `aws rds describe-db-clusters --db-cluster-identifier lex-agents-dev-restored --region eu-west-1 --query "DBClusters[0].Status"` → `"available"`
- [ ] **API health:** `curl -f http://<alb-dr>/health` → `{"status":"ok"}`
- [ ] **Autenticación JWT:** Login con usuario de prueba → token válido devuelto
- [ ] **Consulta básica:** POST `/api/v1/chat` con pregunta regulatoria simple → respuesta con cita verificable
- [ ] **S3 accesible:** Lambda `lex-agents-dev-boe-fetch-raw` puede leer del bucket `lex-agents-raw-dev-dr`
- [ ] **Qdrant disponible:** `curl http://qdrant.lex-agents.local:6333/healthz` → `{"title":"qdrant - 200 ok",...}`
- [ ] **Langfuse trace visible:** Verificar que la consulta de smoke test aparece en Langfuse UI

---

## 7. Procedimiento de rollback a primario

Una vez que eu-central-1 esté recuperada:

### 7.1 Sincronización de datos (si hubo escrituras en DR)

```bash
# Exportar datos creados en DR que no existen en primario
# (solo aplica si usuarios escribieron en el sistema durante el DR)

# Aurora: crear snapshot del cluster DR y copiarlo a eu-central-1
aws rds create-db-cluster-snapshot \
  --db-cluster-identifier lex-agents-dev-restored \
  --db-cluster-snapshot-identifier lex-agents-dev-dr-rollback-$(date +%Y%m%d) \
  --region eu-west-1

# S3: sincronizar objetos creados durante el DR
aws s3 sync \
  "s3://lex-agents-raw-dev-dr" \
  "s3://lex-agents-raw-dev-<account>" \
  --region eu-west-1 \
  --source-region eu-west-1
```

### 7.2 Cutover de vuelta a primario

```bash
# Restaurar registros DNS a eu-central-1
aws route53 change-resource-record-sets \
  --hosted-zone-id "ZXXXXXXXXXXXXX" \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.lex-agents.internal",
        "Type": "CNAME",
        "TTL": 60,
        "ResourceRecords": [{"Value": "<alb-primary-dns>"}]
      }
    }]
  }'
```

### 7.3 Verificar primario

Repetir el [smoke test checklist](#6-smoke-test-checklist-post-restore) contra la región primaria (eu-central-1).

### 7.4 Desactivar recursos DR

```bash
# Una vez confirmado que el primario funciona correctamente:
# Escalar a 0 tasks el ECS service en eu-west-1 (no borrarlo — mantener infraestructura)
aws ecs update-service \
  --cluster lex-agents-dev \
  --service lex-agents-dev-api \
  --desired-count 0 \
  --region eu-west-1

# Detener el cluster Aurora DR (snapshot previo recomendado)
aws rds stop-db-cluster \
  --db-cluster-identifier lex-agents-dev-restored \
  --region eu-west-1
```

---

## 8. Contactos y escalado

| Rol                       | Nombre                            | Canal                                                     | Disponibilidad              |
| ------------------------- | --------------------------------- | --------------------------------------------------------- | --------------------------- |
| Responsable de plataforma | Ignacio Bernal                    | Slack #lex-agents-ops / email ibernale@gruposantander.com | L-V 09:00-18:00 CET         |
| Escalado técnico AWS      | AWS Support (Business/Enterprise) | Console > Support Center                                  | 24/7 (tiempo respuesta SLA) |
| Responsable de negocio    | Por definir en Fase 10            | Por definir                                               | Por definir                 |
| CISO / Riesgo TIC         | Por definir en Fase 10            | Por definir                                               | Por definir                 |

**Matriz de escalado:**

1. Ingeniero de guardia → Responsable de plataforma (si no resuelve en 30 min)
2. Responsable de plataforma → Responsable de negocio (decisión de activar DR)
3. Responsable de plataforma → AWS Support (incidencia en servicios AWS)
4. En caso de incident DORA reportable → CISO + canal de reporte regulatorio

---

## Apéndice A: Bootstrap del vault DR en eu-west-1

Ejecutar **una sola vez** antes del primer backup cross-region:

```bash
# 1. Crear vault en eu-west-1
aws backup create-backup-vault \
  --backup-vault-name lex-agents-dev-dr \
  --region eu-west-1

# 2. Verificar que el plan de backup en eu-central-1 incluye copy action
# (esto requiere modificar el BackupPlan en CDK para incluir copyActions —
#  ver docs/decisions/0051-dr-backup-restore.md para la configuración completa)
```

## Apéndice B: Test DR programado

Realizar DR test simulado en entorno dev cada **6 meses**:

1. Activar el procedimiento completo en entorno dev (sin afectar staging/prod)
2. Medir RTO real vs objetivo
3. Actualizar este documento con lecciones aprendidas
4. Documentar en el registro de pruebas de continuidad de negocio
