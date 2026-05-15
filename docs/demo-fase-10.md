# Demo Fase 10 — Script para Stakeholders Internos Santander

**Duración total:** 45 minutos  
**Audiencia:** Dirección de Tecnología, Legal, Cumplimiento y Operaciones  
**Acceso requerido:** Rol `admin` o `operator` en el entorno de demo

---

## 1. Login (3 min)

**URL:** `/admin-login`

**Pasos:**

1. Abrir la URL de demo. Aparece el formulario de autenticación.
2. Ingresar credenciales con rol `admin`. Mostrar el mensaje de error que aparece con credenciales incorrectas (auditoría de intentos fallidos).
3. Login correcto → redirección automática a `/admin/overview`.
4. Abrir DevTools → Application → sessionStorage: mostrar el JWT almacenado.

**Mensaje clave:** El token JWT incluye el rol del usuario. Toda acción queda ligada a la identidad. No hay sesiones anónimas.

> ⚠️ En producción el SSO corporativo (Cognito, Fase 10.1) sustituirá al login local.

---

## 2. Overview (4 min)

**URL:** `/admin/overview`

**Pasos:**

1. Mostrar el panel de estado global: agentes activos, latencia media, tasa de error.
2. Identificar el indicador de kill switch global (verde = operativo, rojo = plataforma detenida).
3. Navegar por las tarjetas de resumen: consultas procesadas hoy, coste acumulado, alertas pendientes.

**Mensaje clave:** Un vistazo de 10 segundos al Overview es suficiente para saber si la plataforma está sana.

---

## 3. Ops Center (6 min)

**URL:** `/admin/ops`

**Pasos:**

1. Ver la lista de agentes con su estado (verde/ámbar/rojo).
2. Seleccionar un agente individual → activar su kill switch. Confirmar la acción en el diálogo.
3. Observar el cambio de estado en tiempo real.
4. Reactivar el agente.
5. Intentar activar el kill switch **global** con rol `operator` → mostrar que el botón está deshabilitado.
6. Cambiar a sesión `admin` → activar kill switch global → toda la plataforma pasa a rojo.

**Mensaje clave:** Control granular por agente o global. El kill switch global requiere rol `admin` para evitar interrupciones accidentales.

> ⚠️ Kill switch global detiene todos los agentes; el procedimiento de activación debe documentarse en el Audit Trail.

---

## 4. Users & Sesiones (5 min)

**URL:** `/admin/users` → `/admin/users/{username}/sessions`

**Pasos:**

1. Mostrar la lista de usuarios con roles asignados y estado (activo/bloqueado).
2. Buscar un usuario por nombre. Hacer clic en su fila.
3. Navegar a la vista de sesiones del usuario.
4. Identificar una sesión con badge **"Sospechosa"** (la IP de origen cambió durante la sesión).
5. Terminar esa sesión individual. Mostrar la confirmación.

**Mensaje clave:** Visibilidad completa sobre quién está conectado y desde dónde. Las sesiones con cambio de IP se marcan automáticamente para revisión.

---

## 5. Governance (4 min)

**URL:** `/admin/governance`

**Pasos:**

1. Mostrar la lista de propuestas de evolución de prompts pendientes de revisión.
2. Abrir una propuesta: ver el diff entre la versión actual y la propuesta.
3. Aprobar o rechazar la propuesta (con comentario obligatorio).
4. Verificar que el cambio queda registrado en el historial de versiones.

**Mensaje clave:** Ningún prompt de producción cambia sin revisión y aprobación explícita. Trazabilidad completa de quién aprobó qué y cuándo.

---

## 6. Costs & FinOps (4 min)

**URL:** `/admin/costs`

**Pasos:**

1. Ver el desglose de coste por agente en el período actual.
2. Mostrar el gráfico de tendencia semanal.
3. Identificar el agente de mayor coste. Hacer clic para ver su desglose por tipo de llamada.
4. Mostrar el presupuesto configurado y el porcentaje consumido.

**Mensaje clave:** Coste vinculado a cada agente individual. Permite decisiones de optimización basadas en datos reales.

---

## 7. Audit Trail (5 min)

**URL:** `/admin/audit-trail`

**Pasos:**

1. Cargar el audit trail sin filtros: mostrar el volumen de eventos.
2. Filtrar por tipo `user.login.fail`. Mostrar los intentos fallidos con IP y timestamp.
3. Filtrar por `killswitch.global.activate`. Mostrar el evento del paso 3 con el actor y motivo.
4. Seleccionar dos eventos consecutivos: mostrar la verificación de cadena hash (integridad).
5. Exportar el resultado filtrado a CSV.

**Mensaje clave:** Registro inmutable y verificable. Cualquier auditoría regulatoria (DORA, GDPR) puede responderse en minutos.

---

## 8. Observabilidad (6 min)

**URLs:** `/admin/platform/metrics`, `/admin/traces-llm`

**Pasos:**

1. Abrir métricas Prometheus: latencia p50/p95/p99, tasa de errores, throughput.
2. Identificar un pico de latencia en la gráfica y correlacionarlo con un evento del Audit Trail.
3. Navegar a trazas LLM en Langfuse: abrir una traza individual.
4. Mostrar el desglose: tiempo de recuperación RAG, tokens de entrada/salida, coste de la llamada.
5. Mostrar el pipeline de ingestión y su estado.

**Mensaje clave:** Trazabilidad end-to-end desde la petición HTTP hasta la llamada al modelo. Esencial para diagnóstico y optimización.

---

## 9. Feature Flags (4 min)

**URL:** `/admin/flags`

**Pasos:**

1. Mostrar la lista de flags con su estado actual.
2. Desactivar un flag en tiempo real (p. ej., `enable_comparative_analysis`).
3. Abrir la aplicación de usuario en otra pestaña: la funcionalidad afectada desaparece sin redeploy.
4. Reactivar el flag. Verificar que la funcionalidad vuelve inmediatamente.

**Mensaje clave:** Control de funcionalidades en tiempo real sin despliegues. Ideal para rollouts graduales y gestión de incidencias.

---

## 10. Cierre (4 min)

**Resumen de Fase 10:**

- Panel de administración completo con RBAC (viewer / operator / admin).
- Kill switches individuales y global con trazabilidad.
- Audit trail con verificación de integridad por cadena hash.
- Governance de prompts con revisión y aprobación.
- Observabilidad full-stack: métricas, trazas LLM, pipelines.
- Feature flags en tiempo real.
- Gestión de sesiones con detección de anomalías.

**Próximos pasos — Fase 11:**

- Cognito SSO con Active Directory corporativo y MFA obligatorio.
- i18n ES/EN/PT y aislamiento multi-tenant por unidad de negocio.
- Retención GDPR con purga automática y reporting DORA.
- Fine-tuning para regulación bancaria española.

> ⚠️ El SSO corporativo (Cognito) está planificado para Fase 11. Hasta entonces, la autenticación es local con JWT.

---

_Script preparado para demo interna. No distribuir externamente._
