# Guía de Administración — Panel Admin Fase 10

**Versión:** 2.0 (Fase 10)  
**Audiencia:** Administradores y operadores de la plataforma Lex Agents

---

## 1. Acceso y Roles

El panel de administración está disponible en `/admin-login`. El acceso requiere credenciales con rol `operator` o `admin`.

### Matriz de permisos

| Funcionalidad          | viewer | operator | admin |
| ---------------------- | ------ | -------- | ----- |
| Overview (lectura)     | ✅     | ✅       | ✅    |
| Ops Center (lectura)   | ✅     | ✅       | ✅    |
| Kill switch por agente | ❌     | ✅       | ✅    |
| Kill switch global     | ❌     | ❌       | ✅    |
| Gestión de usuarios    | ❌     | ✅       | ✅    |
| Terminar sesiones      | ❌     | ✅       | ✅    |
| Governance (aprobar)   | ❌     | ❌       | ✅    |
| Costs & FinOps         | ❌     | ✅       | ✅    |
| Audit Trail            | ❌     | ✅       | ✅    |
| Observabilidad         | ✅     | ✅       | ✅    |
| Feature Flags          | ❌     | ❌       | ✅    |
| Settings               | ❌     | ❌       | ✅    |

---

## 2. Overview

**URL:** `/admin/overview`

Muestra el estado de salud global de la plataforma en tiempo real:

- **Agentes activos:** número de agentes operativos sobre el total.
- **Latencia media:** p50 y p95 de los últimos 15 minutos.
- **Tasa de error:** porcentaje de peticiones fallidas en la última hora.
- **Consultas procesadas:** contador del día actual.
- **Coste acumulado:** gasto en llamadas a la API del día en curso.

**Indicador de kill switch global:** Un banner prominente indica si la plataforma está operativa (verde) o detenida (rojo). Si está en rojo, ningún agente procesa peticiones.

---

## 3. Ops Center

**URL:** `/admin/ops`

Gestión operativa de los agentes de la plataforma.

### Kill switch por agente

1. Localizar el agente en la lista.
2. Hacer clic en el botón de kill switch de la fila correspondiente.
3. Confirmar en el diálogo (se solicita motivo para el Audit Trail).
4. El estado del agente cambia a rojo inmediatamente.

### Kill switch global

Solo disponible con rol `admin`. Detiene todos los agentes simultáneamente. Ver procedimiento completo en la sección de Seguridad.

### Resync forzado

Permite forzar la recarga de la configuración de un agente sin reiniciarlo. Útil después de cambios en feature flags o prompts aprobados.

---

## 4. Users

**URL:** `/admin/users`

Lista todos los usuarios del sistema con:

- Nombre de usuario y rol asignado.
- Estado de la cuenta (activo/bloqueado).
- Número de sesiones activas.
- Último acceso.

**Búsqueda:** Usar el campo de búsqueda para filtrar por nombre de usuario o rol.

**Bloquear usuario:** El botón de bloqueo desactiva el acceso inmediatamente e invalida todas sus sesiones activas.

---

## 5. Session Management

**URL:** `/admin/users/{username}/sessions`

Vista de todas las sesiones activas de un usuario específico.

### Información de cada sesión

- Token ID (identificador único).
- IP de origen del login inicial.
- IP de la última actividad.
- Timestamp de creación y última actividad.
- Badge **"Sospechosa"** si la IP ha cambiado durante la sesión.

### Acciones disponibles

- **Terminar sesión individual:** invalida el token específico. El usuario recibirá un error 401 en su próxima petición.
- **Terminar todas las sesiones:** invalida todos los tokens del usuario simultáneamente.

> Todas las terminaciones de sesión quedan registradas en el Audit Trail con el actor que realizó la acción.

---

## 6. Governance

**URL:** `/admin/governance`

Flujo de revisión y aprobación de propuestas de evolución de prompts.

### Flujo de revisión

1. Los cambios propuestos aparecen en la lista con estado `pendiente`.
2. Hacer clic en una propuesta para ver el diff completo (versión actual vs. propuesta).
3. Revisar el impacto potencial y los tests de evaluación asociados.
4. **Aprobar:** el prompt pasa a producción en el siguiente despliegue.
5. **Rechazar:** requiere comentario obligatorio que queda registrado.

> Solo el rol `admin` puede aprobar propuestas. Las propuestas rechazadas pueden ser resubmitidas con modificaciones.

---

## 7. Costs & FinOps

**URL:** `/admin/costs`

### Dashboard de costes

- **Por agente:** coste acumulado del período por cada agente.
- **Tendencia:** gráfico semanal comparativo con el período anterior.
- **Desglose:** tokens de entrada/salida, número de llamadas, coste medio por consulta.
- **Presupuesto:** indicador del porcentaje del presupuesto mensual consumido.

**Alertas:** Si un agente supera el umbral de coste configurado, aparece un badge de alerta en su fila.

---

## 8. Audit Trail

**URL:** `/admin/audit-trail`

Registro inmutable de todas las acciones en la plataforma.

### Filtros disponibles

- **Por tipo de acción:** `user.login`, `user.login.fail`, `killswitch.agent.activate`, `killswitch.global.activate`, `session.terminate`, `prompt.approve`, `prompt.reject`, `flag.toggle`.
- **Por usuario:** filtrar por actor de la acción.
- **Por rango de fechas.**

### Verificación de integridad

Cada evento incluye un hash encadenado con el evento anterior. El panel muestra si la cadena es válida (✅) o si se ha detectado una modificación (❌).

**Exportación:** Los resultados filtrados se pueden exportar a CSV para auditorías externas.

---

## 9. Observabilidad

**URLs:** `/admin/platform/metrics`, `/admin/traces-llm`, `/admin/pipelines`, `/admin/aws`

| Sección     | Contenido                                                      |
| ----------- | -------------------------------------------------------------- |
| Métricas    | Latencia p50/p95/p99, tasa de error, throughput (Prometheus)   |
| Trazas LLM  | Detalle por consulta: tokens, coste, tiempo RAG (Langfuse)     |
| Pipelines   | Estado de los pipelines de ingestión de documentos             |
| Consola AWS | Acceso directo a CloudWatch Logs y métricas de infraestructura |

---

## 10. Settings & Feature Flags

**URLs:** `/admin/settings`, `/admin/flags`

### Feature Flags

Los flags controlan la activación de funcionalidades sin necesidad de despliegue. El cambio es efectivo en tiempo real para todos los usuarios.

**Precaución:** Desactivar un flag puede afectar a usuarios activos en ese momento. Comunicar los cambios planificados al equipo antes de ejecutarlos.

### Settings

Configuración de la plataforma: umbrales de alerta, parámetros de ingestión, configuración de notificaciones. Los cambios requieren confirmación y quedan registrados en el Audit Trail.

---

## 11. Seguridad

### Procedimiento Kill Switch Global

1. Acceder a `/admin/ops` con rol `admin`.
2. Hacer clic en "Kill Switch Global".
3. En el diálogo de confirmación, introducir el motivo (texto libre, mínimo 20 caracteres).
4. Confirmar. Todos los agentes se detienen.
5. Documentar el incidente en el canal de guardia.
6. Para reactivar: mismo botón, confirmar reactivación con motivo.

### Revocación de Sesiones ante Incidente

Si se detecta una sesión comprometida:

1. Ir a `/admin/users/{username}/sessions`.
2. Identificar la sesión sospechosa (badge "Sospechosa" o IP anómala).
3. Terminar la sesión individual o todas las sesiones del usuario.
4. Si el riesgo es alto: bloquear la cuenta desde `/admin/users`.
5. Registrar el incidente en el canal de seguridad.

---

_Para onboarding de nuevos administradores, ver `admin-onboarding-playbook.md`._
