# ADR 0033 — Modelo de Roles y Autenticación

- **Estado:** Accepted
- **Fecha:** 2026-05-12
- **Autores:** @ibernale
- **Fase:** 8.0 — Capa de control y observabilidad operacional

---

## Contexto

La autenticación JWT fue activada en Fase 5, pero el sistema opera con un único nivel de acceso efectivo: o tienes token válido o no. No existe distinción entre quien puede leer el historial de consultas y quien puede ejecutar un kill switch.

Con las capacidades de Fase 8 (kill switches, feature flags, audit trail, gestión de fuentes, aprobación de prompts), necesitamos un modelo de control de acceso que:

1. Sea **suficientemente granular** para proteger operaciones destructivas.
2. Sea **simple** de implementar y operar en MVP.
3. Sea **compatible con SSO Santander** cuando llegue Fase 9, sin reescribir el sistema de autorización.

---

## Decisión

**Tres roles en MVP con claims OIDC-compatible para SSO futuro.**

Los roles son **acumulativos**: cada rol hereda todos los permisos del rol anterior.

---

## Definición de roles

### `viewer`

El rol mínimo. Asignado por defecto a usuarios nuevos.

**Puede:**
- Leer el historial de consultas **que él/ella generó** (filtrado por `user_id`).
- Ver el estado de disponibilidad del sistema (UP/DOWN, no detalle técnico).
- Usar la interfaz de consulta.

**No puede:**
- Ver consultas de otros usuarios.
- Ver costes, métricas técnicas ni audit trail.
- Modificar nada.

### `operator`

Rol operacional para el equipo técnico-jurídico.

**Puede (adicional a viewer):**
- Revisar audit samples (marcar como correcto/incorrecto, añadir notas).
- Marcar feedback de calidad en cualquier consulta.
- Ver costes: dashboard de coste por día/agente/modelo.
- Ver métricas técnicas detalladas (latencia, tasas de error, LeMAJ scores).
- Ver el audit trail de operaciones (solo lectura).

**No puede:**
- Cambiar flags de sistema.
- Ejecutar kill switches.
- Aprobar/rechazar PRs de prompts.
- Gestionar usuarios.

### `admin`

Rol de administración del sistema. Reservado a responsables técnicos del proyecto.

**Puede (adicional a operator):**
- Ejecutar kill switches (global y por componente).
- Cambiar feature flags.
- Aprobar o rechazar PRs de prompt evolution.
- Activar/desactivar fuentes de ingesta.
- Forzar re-materialización de assets Dagster.
- Editar memoria semántica (docs/knowledge/) y procedimental (seed SQL).
- Ver y exportar el audit trail completo (incluidas operaciones de todos los usuarios).
- Gestionar usuarios: crear, desactivar, cambiar roles.

**Siempre deja rastro:** todas las acciones admin se registran en `audit_trail` (ADR 0035), incluyendo reason obligatorio para operaciones críticas.

---

## Implementación JWT

El payload JWT incluye un campo `role`:

```json
{
  "sub": "usr_abc123",
  "email": "usuario@gruposantander.com",
  "name": "Nombre Apellido",
  "role": "operator",
  "iat": 1715520000,
  "exp": 1715606400
}
```

El middleware existente (Fase 5) se extiende con un decorador `require_role(min_role)`:

```python
@router.put("/api/v1/admin/state/{key}")
@require_role("admin")
async def update_state(key: str, body: StateUpdateBody, user: User = Depends(get_current_user)):
    ...
```

Los tokens se firman con la misma `JWT_SECRET` existente. No se necesita nueva infraestructura de auth.

---

## Storage de usuarios

Nueva tabla `users` en base de datos separada `data/users.db` (separada de `consultations.db` para aislar responsabilidades):

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,   -- UUID v4
    email           TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,      -- bcrypt, rounds=12
    role            TEXT NOT NULL DEFAULT 'viewer',
    created_at      TEXT NOT NULL,      -- ISO-8601 UTC
    created_by      TEXT,               -- user_id del admin que lo creó
    active          INTEGER NOT NULL DEFAULT 1,  -- 0 = desactivado
    last_login_at   TEXT                -- ISO-8601 UTC, nullable
);
```

**Política de contraseñas:** mínimo 12 caracteres, bcrypt rounds=12. En Fase 9 las contraseñas se sustituyen por tokens SSO; el campo `hashed_password` puede dejarse NULL para usuarios SSO.

---

## Bootstrap

```bash
make admin-bootstrap
```

El script:
1. Verifica que `data/users.db` no existe (no sobreescribe).
2. Lee `BOOTSTRAP_ADMIN_EMAIL` y `BOOTSTRAP_ADMIN_PASSWORD` de env.
3. Crea el primer usuario con `role=admin`.
4. Genera un registro en `audit_trail` con `action_type=user_created, reason=bootstrap`.

---

## Compatibilidad SSO (Fase 9)

El diseño de claims es OIDC-standard:

| Claim JWT interno | Claim OIDC equivalente | Mapeo en Fase 9 |
|---|---|---|
| `sub` | `sub` | UUID del identity provider |
| `email` | `email` | Email corporativo |
| `name` | `name` | Nombre completo |
| `role` | `roles[]` o `groups[]` | Mapeo de grupos AD → roles internos |

En Fase 9, el middleware de auth intercepta el token SSO de Santander, extrae `groups` y mapea al rol interno (`grupo_lex_admin` → `admin`, etc.). El sistema de autorización no cambia: los decoradores `require_role()` funcionan igual.

---

## Alternativas consideradas

| Alternativa | Razón de descarte |
|---|---|
| **RBAC librería externa** (casbin, fastapi-rbac) | Sobredimensionado para 3 roles fijos. Añade dependencia y complejidad de configuración. |
| **Roles en variables de entorno** | No editable en caliente, no soporta múltiples usuarios con roles distintos, no tiene audit trail. |
| **OAuth2 completo ahora** | Prematuro sin SSO Santander. El flujo OAuth2 añade 2–3 servicios adicionales (authorization server, client registration) innecesarios en MVP local. |
| **Un solo rol admin/non-admin** | Insuficiente: los operators necesitan acceso a métricas y audit samples sin poder ejecutar kill switches. El riesgo de operación accidental es real. |

---

## Consecuencias

**Positivas:**
- El modelo de 3 roles es suficientemente granular para el equipo actual y comprensible sin documentación.
- La compatibilidad OIDC garantiza que la adopción de SSO Santander no requiere reescribir el sistema de autorización.
- La separación `users.db` / `consultations.db` facilita backups independientes y auditoría aislada.

**Negativas / Riesgos:**
- Solo bcrypt como factor de autenticación en MVP. En entorno local-only es aceptable; en Fase 9 con acceso de red se necesita 2FA o SSO.
- El campo `role` en JWT no se puede invalidar hasta que expire el token (max 24h). En caso de desactivar un usuario, el sistema debe verificar `active=1` en cada request, no solo el JWT.

**Deuda técnica aceptada:**
- Verificación `active=1` en cada request (no solo en login) — necesaria para que la desactivación de usuario sea efectiva antes de que expire el JWT. Se implementa en sub-fase 8.2.
- UI de gestión de usuarios en Operations Center (sub-fase 8.3).

---

## Referencias

- [ADR 0032](0032-kill-switch-feature-flags.md) — Operaciones que requieren rol `admin`
- [ADR 0034](0034-data-retention.md) — Retención de datos de usuarios
- [ADR 0035](0035-immutable-audit-trail.md) — Audit trail de creación y cambios de usuario
