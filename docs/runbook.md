# Runbook — lex-agents v0.4.0

Operational reference for the lex-agents platform. Covers every task an
operator or admin performs from day-to-day operations to incident response.

> **Auth note:** All `/api/v1/admin/*` endpoints require a bearer token.
> Obtain one with `POST /auth/token` (credentials in `.env` or 1Password).
> Operator role can read; admin role can mutate.

---

## Table of contents

1. [Entorno local](#1-entorno-local)
2. [Sistema — feature flags & kill switches](#2-sistema--feature-flags--kill-switches)
3. [Fuentes de datos](#3-fuentes-de-datos)
4. [Agentes y prompts](#4-agentes-y-prompts)
5. [Auditoría](#5-auditoría)
6. [Costes](#6-costes)
7. [Observabilidad](#7-observabilidad)
8. [Backup y restore](#8-backup-y-restore)
9. [Rotación de credenciales](#9-rotación-de-credenciales)
10. [Emergencias](#10-emergencias)

---

## 1. Entorno local

### 1.1 Levantar desde cero

```bash
# 1. Copiar variables de entorno
cp .env.example .env
# Rellenar: ANTHROPIC_API_KEY, INLABS_API_KEY, SECRET_KEY, ADMIN_PASSWORD

# 2. Arrancar servicios
make dev
# Equivale a: docker compose up --build

# 3. Verificar salud
curl http://localhost:8000/health
# Esperado: {"status":"ok","version":"0.4.0"}
```

Servicios disponibles tras `make dev`:

| Servicio     | URL                         |
|--------------|-----------------------------|
| API          | http://localhost:8000       |
| Web admin    | http://localhost:3000/admin |
| Qdrant UI    | http://localhost:6333       |
| Jaeger UI    | http://localhost:16686      |
| Grafana      | http://localhost:3001       |
| Prometheus   | http://localhost:9090       |

### 1.2 Bootstrap primer admin

```bash
# Crear token admin (requiere .env con ADMIN_PASSWORD y SECRET_KEY)
curl -s -X POST http://localhost:8000/auth/token \
  -d "username=admin&password=${ADMIN_PASSWORD}" \
  | jq -r .access_token
```

El token JWT incluye `role: admin`. Guardarlo para las operaciones siguientes.

### 1.3 Añadir usuario

```bash
# Usuarios se gestionan via .env (USER_CREDENTIALS).
# Formato: "user1:pass1:role1,user2:pass2:role2"
# Roles válidos: admin, operator, user

# Editar .env:
USER_CREDENTIALS="admin:${ADMIN_PASS}:admin,op1:pass:operator,user1:pass:user"

# Reiniciar la API para que tome los nuevos usuarios:
docker compose restart api
```

### 1.4 Cambiar role de usuario

```bash
# Igual que 1.3: editar USER_CREDENTIALS en .env y reiniciar la API.
# El token antiguo del usuario queda inválido hasta que vuelva a hacer login.
```

### 1.5 Detener servicios

```bash
make down          # detiene y elimina contenedores
make down-volumes  # detiene + elimina volúmenes (destruye datos Qdrant)
```

---

## 2. Sistema — feature flags & kill switches

### 2.1 Leer estado del sistema

```bash
TOKEN="<bearer>"
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/system/state | jq
```

Respuesta incluye `feature_flags[]` y `kill_switches[]` con sus estados.

### 2.2 Activar feature flag

```bash
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' \
  http://localhost:8000/api/v1/admin/system/flags/my.feature.flag
# HTTP 204
```

### 2.3 Desactivar feature flag

```bash
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' \
  http://localhost:8000/api/v1/admin/system/flags/my.feature.flag
```

### 2.4 Engage global kill switch

**Efecto:** todas las consultas devuelven HTTP 503 `SYSTEM_KILLED`.
Requiere role `admin` y un motivo obligatorio.

```bash
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "Anomalía detectada: coste +500% en 10 min"}' \
  http://localhost:8000/api/v1/admin/system/kill/global
# HTTP 204
```

También accesible desde la UI: **Admin → botón rojo "Global Kill Switch"**.
Se genera automáticamente una notificación crítica en el centro de notificaciones.

### 2.5 Release global kill switch

```bash
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": false, "reason": "Anomalía confirmada como falso positivo"}' \
  http://localhost:8000/api/v1/admin/system/kill/global
# HTTP 204
```

### 2.6 Engage kill switch de agente específico

```bash
# Targets disponibles: global | consult | rag | export
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "Agente RAG devuelve resultados incorrectos"}' \
  http://localhost:8000/api/v1/admin/system/kill/rag
```

### 2.7 Ver notificaciones del sistema

```bash
# Contar no leídas
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/notifications/count

# Listar todas (últimas 100)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/notifications | jq

# Marcar una como leída
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/notifications/42/read

# Marcar todas como leídas
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/notifications/read-all
```

### 2.8 Inyectar notificación desde webhook externo

El endpoint `POST /api/v1/admin/notifications/ingest` recibe alertas de
Grafana, Langfuse o cualquier sistema externo. Requiere role `admin`.

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "grafana",
    "category": "critical",
    "title": "ServiceDown: API container unhealthy",
    "body": "Container lex-agents-api has been unhealthy for 6 minutes",
    "correlation_id": "grafana-alert-abc123"
  }' \
  http://localhost:8000/api/v1/admin/notifications/ingest
```

---

## 3. Fuentes de datos

### 3.1 Ver estado de fuentes

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/governance/sources | jq
# Campos: source_id, status (active|paused|error), last_sync, doc_count
```

### 3.2 Pausar fuente

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "CENDOJ requiere mantenimiento programado"}' \
  http://localhost:8000/api/v1/admin/governance/sources/cendoj/pause
# HTTP 204 — queda registrado en audit trail
```

Fuentes disponibles: `boe`, `eurlex`, `cendoj`, `inlabs`.

### 3.3 Reanudar fuente

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Mantenimiento completado"}' \
  http://localhost:8000/api/v1/admin/governance/sources/cendoj/resume
```

### 3.4 Forzar resync de un asset Dagster

```bash
# Acceder a Dagster UI (si está desplegado):
open http://localhost:3002

# O via Make:
make ingest-sample

# Verificar que el doc count ha cambiado:
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/governance/sources | jq '.[] | {source_id, doc_count}'
```

### 3.5 Levantar bloqueo CENDOJ quota

Cuando el gauge `lex_cendoj_quota_blocked == 1`:

```bash
# 1. Verificar en Prometheus
curl -s 'http://localhost:9090/api/v1/query?query=lex_cendoj_quota_blocked' | jq

# 2. Si es cuota diaria, esperar reset a 00:00 UTC

# 3. Si es un error permanente, revisar logs de la API:
docker compose logs api | grep cendoj | tail -50

# 4. Reset manual del estado de quota:
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/ops/sources/cendoj/reset-quota
```

### 3.6 Activar fuente comercial (cuando llegue licencia)

```bash
# 1. Añadir credencial en .env:
ARANZADI_API_KEY="..."

# 2. Activar flag:
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' \
  http://localhost:8000/api/v1/admin/system/flags/source.aranzadi.enabled

# 3. Reiniciar ingesta para que se registre la nueva fuente:
make ingest-sample
```

---

## 4. Agentes y prompts

### 4.1 Ver estado de agentes

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/agents | jq
# Campos: agent_id, kill_switch_engaged, active_prompt_version, last_used
```

### 4.2 Ver proposals de prompt evolution

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/governance/proposals | jq
# Campos: proposal_id, agent_id, status (pending|approved|rejected), diff_preview
```

### 4.3 Aprobar PR de prompt evolution

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "comment": "Mejora validada en evals"}' \
  http://localhost:8000/api/v1/admin/governance/proposals/42/decide
```

### 4.4 Rechazar PR de prompt evolution

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "rejected", "comment": "Introduce alucinaciones en benchmark"}' \
  http://localhost:8000/api/v1/admin/governance/proposals/42/decide
```

### 4.5 Rollback de versión de prompt

```bash
# Ver historial de versiones de un agente:
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/ops/agents/specialist_banking/prompts | jq

# Forzar versión anterior:
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version": "v1.2.0", "reason": "Regresión detectada en v1.3.0"}' \
  http://localhost:8000/api/v1/admin/ops/agents/specialist_banking/active-prompt
```

---

## 5. Auditoría

### 5.1 Ver audit trail

```bash
# Últimas 50 entradas
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail?limit=50' | jq

# Filtrar por tipo de acción
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail?action_type=kill_switch.engage' | jq

# Filtrar por actor
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail?actor=admin' | jq
```

### 5.2 Revisar muestras de auditoría del día

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/audit | jq \
  '.[] | select(.created_at | startswith("2026-05"))'
```

### 5.3 Exportar audit trail para auditoría externa

```bash
# Exportar como JSON (últimos 30 días)
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail/export?format=json&days=30' \
  -o "audit_trail_$(date +%Y%m%d).json"

# Exportar como CSV
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail/export?format=csv&days=30' \
  -o "audit_trail_$(date +%Y%m%d).csv"
```

### 5.4 Verificar integridad de cadena del audit trail

Cada entrada tiene un campo `checksum` SHA-256 que encadena el hash de la
entrada anterior. Verificar la cadena:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/audit-trail/verify | jq
# Esperado: {"valid": true, "entries_checked": 1543}
# Si "valid": false → posible tampering. Escalar a seguridad inmediatamente.
```

---

## 6. Costes

### 6.1 Ver dashboard de coste

- **Grafana:** http://localhost:3001 → dashboard "lex-agents / Costs"
- **Prometheus query:** `sum(lex_consultation_cost_usd_total)`
- **Por consulta:** cada `ConsultResponse` incluye `cost_breakdown_by_agent`

```bash
# Coste total acumulado
curl -s 'http://localhost:9090/api/v1/query?query=sum(lex_consultation_cost_usd_total)' | jq

# Coste últimas 24h (tasa por hora)
curl -s 'http://localhost:9090/api/v1/query?query=sum(increase(lex_consultation_cost_usd_total[24h]))' | jq
```

### 6.2 Reconciliar drift > 5%

Drift = diferencia entre coste reportado por la plataforma vs factura Anthropic.

```bash
# 1. Exportar coste acumulado local:
curl -s 'http://localhost:9090/api/v1/query?query=sum(lex_consultation_cost_usd_total)' \
  | jq '.data.result[0].value[1]'

# 2. Comparar con Anthropic Console (manual):
#    https://console.anthropic.com/billing

# 3. Si drift > 5%, revisar trazas costosas:
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/ops/cost-breakdown?top=10' | jq

# 4. Buscar consultas con coste anómalo:
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/ops/cost-breakdown?threshold_usd=0.50' | jq
```

### 6.3 Investigar traza cara

```bash
# Via API (metadata en consulta):
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/consult/<consultation_id> \
  | jq '.cost_breakdown_by_agent'

# Via logs (correlation ID del header X-Correlation-ID de la respuesta):
docker compose logs api | grep "consultation_id=<id>" | grep cost
```

---

## 7. Observabilidad

### 7.1 Acceder a Grafana

```
URL: http://localhost:3001
User: admin / Password: ${GRAFANA_PASSWORD} (en .env)
```

Dashboards disponibles:

- **lex-agents / Overview** — latencia p50/p95, tasa error, consultas/min
- **lex-agents / Costs** — coste diario, tendencia 7d, breakdown por agente
- **lex-agents / Sources** — estado fuentes, errores ingesta, quota CENDOJ
- **lex-agents / Audit** — actividad audit trail, kill switch events

### 7.2 Acceder a Jaeger (trazas distribuidas)

```
URL: http://localhost:16686
Service: lex-agents-api
```

Para buscar una traza por correlation ID:

```bash
# El correlation ID aparece en el header X-Correlation-ID de la respuesta
# Buscar en Jaeger: Service=lex-agents-api, Tags: correlation_id=<value>
```

### 7.3 Acceder a Prometheus

```
URL: http://localhost:9090
```

Métricas de negocio clave:

| Métrica                              | Descripción                          |
|--------------------------------------|--------------------------------------|
| `lex_consultation_cost_usd_total`    | Coste acumulado USD                  |
| `lex_consultation_duration_seconds`  | Latencia p50/p95 por agente          |
| `lex_verification_status_total`      | Verificaciones por status (green/red)|
| `lex_cendoj_quota_blocked`           | 1 si CENDOJ quota bloqueada          |
| `lex_audit_samples_pending`          | Muestras pendientes de revisión      |

### 7.4 Interpretar alertas Tier 1 (críticas)

| Alerta                  | Trigger                               | Acción                               |
|-------------------------|---------------------------------------|--------------------------------------|
| `ServiceDown`           | Contenedor unhealthy > 5 min          | Ver §10.1, reiniciar contenedor      |
| `AnthropicApiErrorRate` | Error rate API > 5% en 10 min         | Ver §10.2, comprobar cuota/incidente |
| `QdrantUnavailable`     | Qdrant no responde > 2 min            | `docker compose restart qdrant`      |
| `DailyCostSpike`        | Coste diario > 2× media 7d            | Ver §10.3, engage kill switch        |
| `CendojQuotaBlocked`    | Gauge `lex_cendoj_quota_blocked==1`   | Ver §3.5                             |

### 7.5 Interpretar alertas Tier 2 (warning)

| Alerta                       | Trigger                        | Acción                                    |
|------------------------------|--------------------------------|-------------------------------------------|
| `LlmP95LatencyHigh`          | p95 latencia > umbral 10 min   | Revisar prompts largos, tokens input      |
| `VerificationFailedRateHigh` | Status=red > 10% en 1h         | Ver §10.4 (alucinaciones)                 |
| `AuditSamplesPendingHigh`    | `audit_samples_pending > 30`   | Revisar muestras en `/admin/audit-trail`  |
| `PromptEvolutionPRsPending`  | Proposals pendientes > 5       | Revisar en `/admin/governance`            |

### 7.6 Reiniciar servicios de observabilidad

```bash
# OTel Collector
docker compose restart otel-collector

# Prometheus (datos en volumen prometheus_data — no se pierden)
docker compose restart prometheus

# Grafana (dashboards provisionados via YAML — no se pierden)
docker compose restart grafana

# Jaeger (datos en memoria — se pierden al reiniciar)
docker compose restart jaeger
```

---

## 8. Backup y restore

### 8.1 Backup SQLite databases

```bash
#!/bin/bash
BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# SQLite WAL mode permite lectura concurrente; no es necesario detener la API
sqlite3 data/consultations.db ".backup $BACKUP_DIR/consultations.db"
sqlite3 data/governance.db    ".backup $BACKUP_DIR/governance.db"

echo "Backup completo en $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
```

### 8.2 Restore SQLite databases

```bash
# Detener la API antes de restaurar
docker compose stop api

# Restaurar
cp backups/20260513_120000/consultations.db data/consultations.db
cp backups/20260513_120000/governance.db    data/governance.db

# Verificar integridad
sqlite3 data/consultations.db "PRAGMA integrity_check;"
sqlite3 data/governance.db    "PRAGMA integrity_check;"

# Reiniciar
docker compose start api
```

### 8.3 Backup Qdrant

```bash
# Crear snapshot via API Qdrant
curl -s -X POST http://localhost:6333/snapshots | jq

# Listar snapshots disponibles
curl -s http://localhost:6333/snapshots | jq

# Copiar snapshot fuera del contenedor
SNAPSHOT=$(curl -s http://localhost:6333/snapshots | jq -r '.result[-1].name')
docker compose cp qdrant:/qdrant/snapshots/$SNAPSHOT "backups/$SNAPSHOT"
```

### 8.4 Restore Qdrant

```bash
# 1. Detener Qdrant
docker compose stop qdrant

# 2. Copiar snapshot al contenedor
docker compose cp "backups/$SNAPSHOT" qdrant:/qdrant/snapshots/$SNAPSHOT

# 3. Arrancar Qdrant con flag de restore
docker compose run --rm qdrant ./qdrant --snapshot /qdrant/snapshots/$SNAPSHOT

# 4. Verificar colecciones
curl -s http://localhost:6333/collections | jq
```

---

## 9. Rotación de credenciales

### 9.1 Rotar API key de Anthropic

```bash
# 1. Crear nueva key en https://console.anthropic.com/settings/keys
# 2. Actualizar .env: ANTHROPIC_API_KEY=sk-ant-new-key
# 3. Reiniciar API:
docker compose restart api
# 4. Verificar que consultas funcionan:
curl -s -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8000/api/v1/consult \
  -H "Content-Type: application/json" \
  -d '{"query": "Capital Tier 1 CRR", "jurisdiction": "ES"}' | jq .status
# 5. Revocar key antigua en Anthropic Console
```

### 9.2 Rotar API key INLABS

```bash
# 1. Renovar en https://inlabs.boe.es (acceso corporativo)
# 2. Actualizar .env: INLABS_API_KEY=nueva_key
# 3. docker compose restart api
# 4. Verificar ingesta: make ingest-sample
```

### 9.3 Rotar SECRET_KEY (JWT)

```bash
# AVISO: invalida todos los tokens activos — hacer en ventana de mantenimiento.

# 1. Generar nueva clave:
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Actualizar .env: SECRET_KEY=nueva_clave
# 3. docker compose restart api
# 4. Todos los usuarios deberán re-autenticarse.
```

### 9.4 Rotar password de admin

```bash
# Editar USER_CREDENTIALS en .env con nueva contraseña:
# Formato: "admin:nueva_pass:admin,..."
docker compose restart api
```

---

## 10. Emergencias

### 10.1 Sistema responde lento: diagnóstico

```bash
# 1. Verificar latencia p95 actual:
curl -s 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,rate(http_request_duration_seconds_bucket[5m]))' | jq

# 2. Verificar recursos del contenedor API:
docker stats lex-agents-api --no-stream

# 3. Revisar logs por errores:
docker compose logs api --tail=100 | grep -E "ERROR|CRITICAL|timeout"

# 4. Si Qdrant es el cuello de botella:
docker stats lex-agents-qdrant --no-stream

# 5. Si el problema persiste y afecta a usuarios, engage kill switch (§2.4)
```

### 10.2 Coste se dispara: detectar consulta culpable

```bash
# 1. Alerta DailyCostSpike activa — ir a Grafana dashboard "Costs"

# 2. Identificar consultas costosas en las últimas 2h:
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/ops/cost-breakdown?top=20&window_minutes=120' | jq

# 3. Si hay un patrón (mismo usuario, mismo agente):
#    a. Engage kill switch del agente específico (§2.6)
#    b. Revisar si es un bucle de prompts o abuso

# 4. Si es coste legítimo pero alto, revisar límite de tokens en .env:
#    MAX_TOKENS_PER_CONSULTATION
```

### 10.3 Qdrant fuera de servicio: recuperación

```bash
# 1. Verificar estado:
curl -s http://localhost:6333/readyz

# 2. Intentar reinicio graceful:
docker compose restart qdrant

# 3. Si el volumen está corrupto, restaurar desde backup (§8.4)

# 4. Mientras Qdrant está caído, engage kill switch para dar error claro a usuarios.

# 5. Verificar colecciones tras restaurar:
curl -s http://localhost:6333/collections | jq
make ingest-sample  # re-ingestar si las colecciones están vacías
```

### 10.4 Alucinaciones aumentan: workflow de mitigación

Indicador: alerta `VerificationFailedRateHigh` o tasa `verification_status=red > 10%`.

```bash
# 1. Cuantificar:
curl -s 'http://localhost:9090/api/v1/query?query=sum(rate(lex_verification_status_total{status="red"}[1h]))/sum(rate(lex_verification_status_total[1h]))' | jq

# 2. Identificar qué agente falla más:
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/audit?verification_status=red&limit=50' | jq \
  '.[] | {agent_id, consultation_id}'

# 3. Revisar si hay un prompt evolution reciente:
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/governance/proposals?status=approved&limit=5' | jq

# 4. Si el problema coincide con un prompt reciente, hacer rollback (§4.5)

# 5. Mientras tanto, engage kill switch del agente afectado (§2.6)

# 6. Ejecutar evals para confirmar regresión:
make eval-quick
```

### 10.5 Fuente devuelve errores masivos

```bash
# 1. Identificar fuente problemática:
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/governance/sources | jq '.[] | select(.status=="error")'

# 2. Ver últimos errores:
docker compose logs api | grep "source_id=boe" | grep ERROR | tail -20

# 3. Pausar la fuente para evitar reintentos (§3.2)

# 4. Verificar que consultas siguen funcionando con otras fuentes:
curl -s -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:8000/api/v1/consult \
  -H "Content-Type: application/json" \
  -d '{"query": "Capital Tier 1 CRR", "jurisdiction": "ES"}' | jq .verification_status

# 5. Cuando la fuente externa se recupere, reanudar (§3.3)
```

### 10.6 Datos personales potencialmente filtrados: contención

```bash
# 1. Engage kill switch global INMEDIATAMENTE:
curl -s -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"engage": true, "reason": "INCIDENTE SEGURIDAD: posible filtración PII — contención"}' \
  http://localhost:8000/api/v1/admin/system/kill/global

# 2. Identificar la consulta problemática via audit trail:
curl -s -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/admin/audit-trail?limit=100' | jq \
  '.[] | select(.action_type == "consult.response")'

# 3. Exportar audit trail completo para análisis forense (§5.3)

# 4. Verificar que los logs no contienen PII (redactor activo en prod):
docker compose logs api | grep -iE "nif|dni|nombre|email" | wc -l
# Debería ser 0 en prod (enable_pii_redaction=True)

# 5. Escalar a DPO (Santander) y al equipo de seguridad.
#    RGPD Art. 33 — notificación a AEPD en 72h si hay brecha confirmada.

# 6. Una vez contenido, release kill switch y documentar en audit trail.
```
