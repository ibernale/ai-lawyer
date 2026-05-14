# DORA Evidence Pack — lex-agents

**Regulación:** EU 2022/2554 (DORA) — Digital Operational Resilience Act
**Aplicabilidad:** Plataforma lex-agents desplegada en AWS (workloads-dev / workloads-pre)
**Revisión:** Trimestral + automática diaria
**Owner:** Platform Team — Ignacio Bernal (ignacio.bernal@gruposantander.com)

---

## 1. Resumen ejecutivo

Este documento describe la estructura del evidence pack de compliance DORA para
lex-agents. Las evidencias se recopilan de dos formas:

| Tipo | Frecuencia | Fuente | Ubicación en S3 |
|------|------------|--------|-----------------|
| **Automática** | Diaria (02:00 UTC) | Lambda `evidence_collector` | `evidence/{YYYY-MM-DD}/{check}.json` |
| **Resumen diario** | Diaria (02:00 UTC) | Lambda `evidence_collector` | `reports/{YYYY-MM-DD}/summary.md` |
| **Manual trimestral** | Trimestral | Auditoría humana | `manual/{YYYY-Q{N}}/evidence.md` |

**Bucket:** `s3://lex-agents-{env}-compliance-docs-{account-id}/`
**Retención:** Object Lock COMPLIANCE, 7 años (DORA Art. 28 ICT record keeping)
**Cifrado:** SSE-KMS con CMK `/alias/lex-agents-{env}-s3`

---

## 2. Checks automatizados (evidence_collector Lambda)

El Lambda `evidence_collector` ejecuta los siguientes checks y genera un score
de compliance entre 0 y 100%:

### 2.1 KMS Key Rotation (`kms_rotation_enabled`)

**Artículo DORA:** Art. 9.3 — Encryption controls
**Baseline esperado:** Todas las CMK del account tienen rotación anual activada

Campos del evidence JSON:
```json
{
  "check": "kms_rotation_enabled",
  "total_cmks": 5,
  "non_rotating": [],
  "passed": true
}
```

Acción si falla: activar rotación vía CDK (`enableKeyRotation: true`) o:
```bash
aws kms enable-key-rotation --key-id <KEY_ID> --profile lex-agents-dev
```

---

### 2.2 CloudTrail (`cloudtrail_enabled`)

**Artículo DORA:** Art. 10.2 — Logging and monitoring
**Baseline esperado:** Trail multi-región activo con log file validation

Campos del evidence JSON:
```json
{
  "check": "cloudtrail_enabled",
  "trails_found": 1,
  "multi_region_trails": 1,
  "is_logging": true,
  "passed": true
}
```

Acción si falla:
```bash
aws cloudtrail start-logging --name <TRAIL_ARN> --profile lex-agents-management
```

---

### 2.3 GuardDuty (`guardduty_enabled`)

**Artículo DORA:** Art. 10.1 — Detection controls; Art. 17 — Incident management
**Baseline esperado:** Detector activo, 0 findings HIGH/CRITICAL sin resolver

Campos del evidence JSON:
```json
{
  "check": "guardduty_enabled",
  "detector_enabled": true,
  "high_critical_findings": 0,
  "passed": true
}
```

Acción si hay findings HIGH/CRITICAL: ver runbook §11.4 (Investigar GuardDuty findings).

---

### 2.4 AWS Config Compliance (`config_compliance`)

**Artículo DORA:** Art. 8.1 — ICT asset management; Art. 8.4 — Change management
**Baseline esperado:** Recorder activo, ≥ 80% de reglas en estado COMPLIANT

Campos del evidence JSON:
```json
{
  "check": "config_compliance",
  "recorder_active": true,
  "compliant_rules": 47,
  "non_compliant_rules": 3,
  "compliance_pct": 94.0,
  "passed": true
}
```

Acción si compliance < 80%: revisar reglas no-compliant en AWS Config Console →
Security account → Config → Rules.

---

## 3. ComplianceScore métrica y alarma

El Lambda publica la métrica `ComplianceScore` en CloudWatch namespace
`LexAgents/Compliance`. Una alarma dispara al SNS alert topic si el score
cae por debajo de **90%**.

```
Alarma:  lex-agents-{env}-compliance-score-low
Métrica: LexAgents/Compliance / ComplianceScore
Umbral:  < 90%
Acción:  SNS → Alert Router Lambda → Slack
```

---

## 4. Acceso a evidencias históricas

### 4.1 AWS Console

```
S3 → lex-agents-{env}-compliance-docs-{account} → evidence/ → {fecha}/
```

### 4.2 AWS CLI

```bash
# Listar reportes del mes actual
aws s3 ls s3://lex-agents-dev-compliance-docs-123456789012/reports/ \
  --profile lex-agents-dev

# Descargar resumen de fecha específica
aws s3 cp \
  s3://lex-agents-dev-compliance-docs-123456789012/reports/2026-05-14/summary.md \
  ./dora-summary-2026-05-14.md \
  --profile lex-agents-dev

# Descargar todos los evidences de un día
aws s3 cp \
  s3://lex-agents-dev-compliance-docs-123456789012/evidence/2026-05-14/ \
  ./evidence-2026-05-14/ \
  --recursive \
  --profile lex-agents-dev
```

### 4.3 Amazon Athena (consultas ad-hoc para auditoría externa)

El bucket está habilitado para consultas Athena. Para crear la tabla externa:

```sql
CREATE EXTERNAL TABLE dora_evidence (
  `check` string,
  total_cmks int,
  non_rotating array<string>,
  compliant_rules int,
  non_compliant_rules int,
  compliance_pct double,
  passed boolean,
  error string
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://lex-agents-dev-compliance-docs-123456789012/evidence/'
TBLPROPERTIES ('has_encrypted_data'='true');
```

Consulta de tendencia:
```sql
SELECT
  date_parse(split_part("$path", '/', 5), '%Y-%m-%d') AS evidence_date,
  SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS checks_passed,
  COUNT(*) AS total_checks
FROM dora_evidence
GROUP BY 1
ORDER BY 1 DESC
LIMIT 90;
```

---

## 5. Checklist de auditoría trimestral (manual)

Para cada auditoría trimestral, un miembro del equipo con rol `SecurityAuditAccess`
en IAM Identity Center debe completar los siguientes puntos y firmar el documento
en `manual/{YYYY-Q{N}}/evidence.md`:

### 5.1 Controles automatizables (verificar que el Lambda pasó los últimos 90 días)

```bash
# Descargar últimos 90 días de reportes diarios y verificar score >= 90
aws s3 cp s3://lex-agents-dev-compliance-docs-{account}/reports/ ./reports/ \
  --recursive --profile lex-agents-dev
grep -h "Score:" ./reports/*/summary.md | sort
```

- [ ] ComplianceScore ≥ 90% en ≥ 85% de los días del trimestre
- [ ] 0 días con HIGH/CRITICAL GuardDuty findings sin resolver
- [ ] KMS rotation activa en todas las CMK

### 5.2 Controles que requieren verificación manual

**Art. 9.2 — IAM MFA enforcement:**
```bash
aws iam generate-credential-report --profile lex-agents-management
aws iam get-credential-report --profile lex-agents-management \
  --query 'Content' --output text | base64 -d | grep -v mfa_active:true
# No debe haber usuarios con consola sin MFA
```

- [ ] 0 usuarios IAM con acceso consola sin MFA activo

**Art. 9.4 — Network segmentation:**
```bash
aws ec2 describe-security-groups \
  --filters "Name=ip-permission.cidr,Values=0.0.0.0/0" \
  --query 'SecurityGroups[?IpPermissions[?IpRanges[?CidrIp==`0.0.0.0/0`] && FromPort!=`443`]].[GroupId,GroupName]' \
  --profile lex-agents-dev
# No debe haber SGs con 0.0.0.0/0 en puertos distintos de 443
```

- [ ] 0 SGs con ingress 0.0.0.0/0 en puertos != 443

**Art. 10.2 — CloudTrail log integrity:**
```bash
aws cloudtrail validate-logs \
  --trail-arn <TRAIL_ARN> \
  --start-time $(date -d '90 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --profile lex-agents-management
# Esperado: 0 invalid log files, 0 missing log files
```

- [ ] CloudTrail log integrity validation: 0 invalid/missing files

**Art. 11.2 — Backup verification:**
```bash
# Verificar que AWS Backup ha ejecutado al menos un backup exitoso
aws backup list-backup-jobs \
  --by-state COMPLETED \
  --by-created-after $(date -d '30 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --profile lex-agents-dev \
  | jq '.BackupJobs | length'
# Debe ser > 0
```

- [ ] AWS Backup: al menos 1 backup Aurora completado en los últimos 30 días

**Art. 11.1 — DR plan validation:**
- [ ] `docs/aws/dr-plan.md` revisado y sin cambios pendientes
- [ ] RTO/RPO documentados cumplen el objetivo del trimestre

**Art. 28 — Terceros ICT:**
- [ ] AWS Enterprise Support SLA vigente
- [ ] Anthropic/Bedrock DPA actualizada
- [ ] Registro de proveedores ICT actualizado en Santander GRC

### 5.3 Firma de la auditoría

```markdown
## Firma de auditoría

| Campo | Valor |
|-------|-------|
| Auditor | [Nombre y cargo] |
| Fecha | YYYY-MM-DD |
| Período cubierto | Q{N} YYYY (YYYY-MM-DD — YYYY-MM-DD) |
| Resultado | PASS / PASS con observaciones / FAIL |
| Observaciones | [Si las hay] |
| Próxima revisión | YYYY-MM-DD |
```

---

## 6. Procedimiento de escalado ante fallo de compliance

Si el ComplianceScore cae por debajo de 90% o si la auditoría trimestral
detecta un fallo en un control DORA:

1. **Alerta automática** → Slack `#lex-agents-alerts` vía Alert Router Lambda
2. **Acknowledge** → El oncall confirma recepción en < 30 minutos
3. **Investigación** → Revisar el report S3 para identificar el check fallido
4. **Remediación** → Aplicar la acción correctiva documentada en §2.x
5. **Verificación** → Esperar próxima ejecución del Lambda (02:00 UTC) o ejecutar manualmente:
   ```bash
   aws lambda invoke \
     --function-name lex-agents-dev-evidence-collector \
     --profile lex-agents-dev \
     /tmp/evidence-result.json
   cat /tmp/evidence-result.json
   ```
6. **Documentación** → Registrar el incidente en `docs/compliance/incidents/{YYYY-MM-DD}.md`

---

## 7. Mapa de evidencias → artículos DORA

| Check automático / control manual | Artículo DORA | Periodicidad |
|-----------------------------------|---------------|--------------|
| `kms_rotation_enabled` | Art. 9.3 Encryption | Diaria |
| `cloudtrail_enabled` | Art. 10.2 Logging | Diaria |
| `guardduty_enabled` | Art. 10.1 Detection | Diaria |
| `config_compliance` | Art. 8.1, 8.4 Risk mgmt | Diaria |
| IAM MFA coverage | Art. 9.2 Access control | Trimestral |
| SG no 0.0.0.0/0 | Art. 9.4 Network | Trimestral |
| CloudTrail log validation | Art. 10.2 Audit | Trimestral |
| AWS Backup completado | Art. 11.2 Recovery | Trimestral |
| DR plan reviewed | Art. 11.1 Continuity | Trimestral |
| ICT provider register | Art. 28 Third-party | Trimestral |
| Audit Manager DORA assessment | Arts. 8–11 (agregado) | Trimestral |
| Security Hub DORA insights | Arts. 9, 10 | Continuo |

---

*Documento mantenido por el Platform Team. Actualizar en cada release mayor.*
*Versión: 0.5.0 — 2026-05-14*
