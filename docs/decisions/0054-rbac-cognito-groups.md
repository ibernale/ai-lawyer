# 0054 — Migración del RBAC a Cognito Groups

**Status:** Accepted  
**Date:** 2026-05-15

## Context

El RBAC actual (ADR 0033) define cuatro roles en
`packages/admin/src/lex_agents_admin/rbac.py`: `analyst < auditor < operator < admin`.
Los roles se almacenan en el payload del JWT HS256 generado internamente.

La adopción de Cognito como sistema de identidad (ADR 0053) requiere migrar
la fuente del role al token JWT de Cognito. Cognito organiza la asignación de
permisos mediante **Cognito Groups**, que se incluyen en el claim estándar
`cognito:groups` del ID token.

Esta migración es la oportunidad para consolidar los cuatro roles actuales en
tres roles operacionales más claros, eliminando la distinción analyst/auditor
que ha generado confusión en la operativa diaria.

## Decision

### Consolidación de roles: 4 → 3

Los cuatro roles actuales se consolidan en tres Cognito Groups:

| Grupo Cognito | Precedence | Sustituye a          |
|---------------|-----------|----------------------|
| `admin`       | 1         | `admin`              |
| `operator`    | 2         | `operator` + `auditor` |
| `viewer`      | 3         | `analyst`            |

**Criterio de consolidación:**

- `analyst` → `viewer`: el analyst solo podía consultar. Viewer refleja mejor
  la naturaleza de ese acceso (lectura de sus propias consultas y health pública).
- `auditor` → `operator`: el auditor podía leer el audit trail y governance
  decisions. Esas capacidades se corresponden con el operator de Fase 10.
  El auditor no tenía capacidad de escritura — se mantiene esa restricción
  dentro de operator.
- `operator` → `operator`: sin cambios funcionales.
- `admin` → `admin`: sin cambios funcionales.

La precedencia numérica de Cognito Groups resuelve conflictos cuando un usuario
está en varios grupos: el grupo con precedence más baja (número menor) gana.
En la práctica, un usuario no debería estar en más de un grupo; si ocurre, el
sistema aplica el grupo de mayor privilegio.

### Matriz de permisos Fase 10

| Capacidad                                        | viewer | operator | admin |
|--------------------------------------------------|--------|----------|-------|
| Realizar consultas jurídicas                     | ✓      | ✓        | ✓     |
| Ver sus propias consultas                        | ✓      | ✓        | ✓     |
| Ver health pública (`GET /health`)               | ✓      | ✓        | ✓     |
| Ver audit trail completo                         | ✗      | ✓        | ✓     |
| Revisar audit samples                            | ✗      | ✓        | ✓     |
| Ver métricas técnicas (Grafana / Langfuse)       | ✗      | ✓        | ✓     |
| Ver costes (FinOps dashboard)                    | ✗      | ✓        | ✓     |
| Ver governance proposals                         | ✗      | ✓        | ✓     |
| Aprobar prompt evolution proposals               | ✗      | ✗        | ✓     |
| Cambiar feature flags                            | ✗      | ✗        | ✓     |
| Activar / desactivar kill switches               | ✗      | ✗        | ✓     |
| Gestionar fuentes (pause/resume/resync)          | ✗      | ✗        | ✓     |
| Gestionar usuarios (invitar/desactivar)          | ✗      | ✗        | ✓     |
| Ver audit trail de usuario completo              | ✗      | ✗        | ✓     |
| Exportar audit trail                             | ✗      | ✗        | ✓     |

### Integración con el backend existente

El decorador `require_role(*roles)` en
`packages/admin/src/lex_agents_admin/rbac.py:32` **no cambia de firma**.
Solo cambia la fuente del role en el contexto de autenticación:

- **Antes:** role extraído del claim `role` en el JWT HS256 generado internamente.
- **Después:** role extraído del claim `cognito:groups` en el ID token de Cognito.
  Se toma el grupo de mayor privilegio si el usuario está en varios.

El middleware de auth (`apps/api/src/lex_agents_api/auth.py`) es el único
componente que cambia: pasa de verificar con `jwt_secret` (HS256) a verificar
con el JWKS endpoint de Cognito (RS256).

### Migración de usuarios existentes

Para cada usuario en `AUTH_USERS_JSON` (env var actual):

1. Crear usuario en Cognito User Pool via `AdminCreateUser` API:
   - `Username`: dirección email del usuario.
   - `TemporaryPassword`: generada aleatoriamente (mínimo 14 chars).
   - `MessageAction: SUPPRESS` (el email de bienvenida lo gestiona lex-agents,
     no Cognito directamente — ver ADR 0055).
2. Asignar al grupo correspondiente via `AdminAddUserToGroup`.
3. Marcar usuario como `FORCE_CHANGE_PASSWORD` (estado por defecto de
   `AdminCreateUser`).
4. Enviar email de activación con token único de 72h (ver ADR 0059).
5. Tras verificar que todos los usuarios han activado su cuenta en Cognito,
   eliminar `AUTH_USERS_JSON` del entorno y `scripts/admin_bootstrap.py`.

**Rollback:** si la migración falla, `AUTH_USERS_JSON` sigue activo. El
backend puede configurarse con un feature flag para aceptar ambos métodos
de autenticación durante la ventana de migración.

## Alternatives considered

**Mantener 4 roles y mapear 1:1 a Cognito Groups:**

- Pro: cero cambio en permisos existentes.
- Con: el rol `auditor` ha demostrado ser confuso operativamente (los operators
  asumen que también pueden leer audit trail; los auditors asumen que pueden
  hacer más de lo que pueden).
- Rechazado: la migración es el momento natural para limpiar esta ambigüedad.

**Usar Cognito custom attributes en lugar de Groups para el rol:**

- Pro: más flexible, permite roles por recurso.
- Con: los custom attributes no se incluyen automáticamente en el claim
  `cognito:groups`; requieren lógica adicional en un Pre Token Generation
  Lambda trigger.
- Rechazado: Groups es el mecanismo estándar de Cognito para RBAC; menor
  complejidad operativa.

**Implementar ABAC (Attribute-Based Access Control):**

- Pro: permisos más granulares (por cliente, por materia jurídica, etc.).
- Con: complejidad alta; no existe requisito actual que lo justifique.
- Rechazado para Fase 10; puede revisarse en H3 si surge necesidad de
  multi-tenancy por área de negocio.

## Consequences

**Positivo:**

- La fuente de verdad del role es Cognito (auditado, con historial de cambios
  en CloudTrail).
- Cambios de role son inmediatos en el siguiente refresh de token (1h máximo
  de lag con los tokens actuales).
- El decorador `require_role` no cambia — los 15+ endpoints ya decorados
  funcionan sin modificación.
- La simplificación a 3 roles reduce ambigüedad en formación y onboarding.

**Negativo:**

- Se pierde el rol `auditor` como entidad diferenciada. Los auditores
  de cumplimiento que solo debían leer el audit trail ahora tienen capacidades
  de operator adicionales. Si esto es un problema, se puede reintroducir
  `auditor` como cuarto grupo en una sub-fase posterior.
- La ventana de migración requiere que los usuarios existentes completen el
  flujo de activación (cambio de contraseña + MFA) antes de que se desactive
  `AUTH_USERS_JSON`. Usuarios que no completen en 72h deben ser reinvitados.
