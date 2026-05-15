# Playbook de Onboarding para Nuevos Administradores

**Versión:** 1.0 (Fase 10)  
**Audiencia:** Nuevos administradores y operadores de Lex Agents  
**Tiempo estimado:** 2-3 horas para completar el playbook

---

## 1. Prerrequisitos

Antes de comenzar, verifica que tienes lo siguiente:

### Accesos necesarios

- [ ] **Cuenta AWS** con acceso a la cuenta de Lex Agents (solicitar al equipo de Cloud).
- [ ] **Rol en AUTH_USERS_JSON:** Tu usuario debe estar configurado con rol `admin` u `operator`. Verificar con el Tech Lead actual.
- [ ] **VPN corporativa:** El panel de administración solo es accesible desde la red interna o VPN.
- [ ] **Acceso a Langfuse:** Solicitar al equipo de Observabilidad.
- [ ] **Canal de guardia:** Unirte al canal de Slack/Teams de guardia de operaciones de Lex Agents.

### Documentación previa a leer

- `docs/architecture.md` — Visión general del sistema.
- `docs/admin-guide-v2.md` — Referencia completa del panel de administración.
- `docs/incident-response.md` — Procedimientos de respuesta a incidentes.

---

## 2. Primer Login y Verificación de Acceso

### Paso 1: Acceder al panel

1. Conectarse a la VPN corporativa.
2. Abrir la URL del entorno de staging (el Tech Lead te la proporcionará).
3. Acceder a `/admin-login` con tus credenciales.

### Paso 2: Verificar tu rol

1. Tras el login, ir a `/admin/overview`.
2. Verificar que puedes ver todos los paneles correspondientes a tu rol (ver matriz de permisos en `admin-guide-v2.md`).
3. Si alguna sección está inaccesible y debería estar disponible, contactar con el Tech Lead.

### Paso 3: Verificar tu presencia en el Audit Trail

1. Ir a `/admin/audit-trail`.
2. Filtrar por tu nombre de usuario.
3. Deberías ver el evento `user.login` de los pasos anteriores.

> ✅ Si ves tus propias acciones en el Audit Trail, el acceso está configurado correctamente.

---

## 3. Entender el Kill Switch

El kill switch es la herramienta de intervención de emergencia de la plataforma. **Úsalo solo cuando sea estrictamente necesario.**

### ¿Qué hace el kill switch?

- **Kill switch por agente:** Detiene un agente específico. Las peticiones a ese agente reciben error 503. El resto de la plataforma sigue operativa.
- **Kill switch global:** Detiene **todos** los agentes simultáneamente. Ninguna consulta es procesada hasta la reactivación.

### ¿Cuándo usarlo?

**Kill switch por agente:**

- El agente está generando respuestas incorrectas de forma sistemática.
- Se detecta un consumo anómalo de tokens en un agente específico.
- Un agente tiene una vulnerabilidad identificada que requiere intervención inmediata.

**Kill switch global (solo admin):**

- Brecha de seguridad activa en la plataforma.
- Fallo crítico que afecta a todos los agentes.
- Instrucción explícita de la dirección de Seguridad o Tecnología.

### Cómo documentar el motivo

**Todo kill switch debe documentarse.** El sistema obliga a introducir un motivo en el momento de la activación (mínimo 20 caracteres). Adicionalmente:

1. Enviar mensaje al canal de guardia con: quién, qué, cuándo, por qué.
2. Abrir un ticket en el sistema de incidencias con los detalles.
3. Notificar al Tech Lead y al responsable del turno.

### Ejercicio de práctica

En el entorno de **staging**, practica el flujo completo:

1. Activar el kill switch de un agente de prueba.
2. Verificar que el evento aparece en el Audit Trail.
3. Reactivar el agente.
4. Confirmar que el estado vuelve a verde.

> ⚠️ Nunca practicar con el kill switch en el entorno de producción.

---

## 4. Revisar el Audit Trail de tus Propias Acciones

El Audit Trail es tu herramienta principal para verificar que tus acciones se registran correctamente y para auditar el comportamiento de la plataforma.

### Práctica recomendada (primer día)

1. Ir a `/admin/audit-trail`.
2. Filtrar por tu nombre de usuario.
3. Revisar todos los eventos generados durante tu sesión de onboarding.
4. Verificar que el hash de cadena es válido (✅) en todos los eventos.

### Acciones que generan eventos de audit

| Acción                       | Tipo de evento               |
| ---------------------------- | ---------------------------- |
| Login exitoso                | `user.login`                 |
| Login fallido                | `user.login.fail`            |
| Activar kill switch agente   | `killswitch.agent.activate`  |
| Activar kill switch global   | `killswitch.global.activate` |
| Terminar sesión de usuario   | `session.terminate`          |
| Aprobar propuesta de prompt  | `prompt.approve`             |
| Rechazar propuesta de prompt | `prompt.reject`              |
| Toggle de feature flag       | `flag.toggle`                |

---

## 5. Contactos de Escalada y Procedimientos de Emergencia

### Contactos principales

| Rol                      | Responsabilidad                                       | Canal de contacto                        |
| ------------------------ | ----------------------------------------------------- | ---------------------------------------- |
| Tech Lead                | Escalada técnica, accesos, decisiones de arquitectura | Canal Slack #lex-agents-tech             |
| Responsable de Seguridad | Incidentes de seguridad, brechas, anomalías           | Canal Slack #security-incidents          |
| Product Manager          | Decisiones de negocio, comunicación con stakeholders  | Email directo                            |
| Equipo de Cloud (AWS)    | Problemas de infraestructura, accesos AWS             | Canal Slack #cloud-ops                   |
| Guardia de operaciones   | Incidentes fuera de horario laboral                   | Teléfono de guardia (consultar intranet) |

### Árbol de escalada en emergencias

```
Incidente detectado
    │
    ├─ ¿Brecha de seguridad activa?
    │   └─ SÍ → Kill switch global + Notificar Seguridad INMEDIATAMENTE
    │
    ├─ ¿Fallo crítico de un agente?
    │   └─ SÍ → Kill switch del agente + Notificar Tech Lead
    │
    └─ ¿Comportamiento anómalo sin impacto inmediato?
        └─ SÍ → Documentar + Notificar Tech Lead en horario laboral
```

### Procedimiento de emergencia fuera de horario

1. Activar kill switch si hay riesgo activo.
2. Documentar en el Audit Trail (el sistema registra automáticamente).
3. Enviar mensaje al canal de guardia.
4. Llamar al teléfono de guardia si no hay respuesta en 15 minutos.
5. El Tech Lead de guardia tomará el relevo y coordinará la respuesta.

---

## Lista de verificación de onboarding completado

- [ ] Primer login exitoso y rol verificado.
- [ ] Revisado el Audit Trail con eventos propios.
- [ ] Practicado kill switch en staging.
- [ ] Unido al canal de guardia.
- [ ] Leído `incident-response.md`.
- [ ] Contactos de escalada guardados.
- [ ] Revisado la matriz de permisos de rol propio.

---

_Una vez completado este playbook, comunícalo al Tech Lead para que quede registrado._
