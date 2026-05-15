# 0055 — Onboarding flow

**Status:** Accepted  
**Date:** 2026-05-15

## Context

Con Cognito como sistema de identidad (ADR 0053) y signup público
deshabilitado, todo alta de usuario debe pasar por el administrador.
Es necesario definir el flujo completo: desde la decisión de invitar a
alguien hasta el primer uso efectivo de la plataforma.

El flujo debe:
- Ser completamente trazable (cada paso auditado).
- Minimizar la fricción para el usuario final (primer login guiado).
- No depender de que el admin y el usuario estén en línea al mismo tiempo.
- Soportar el caso de token expirado sin requerir crear una cuenta nueva.

## Decision

El alta de usuario es siempre **admin-driven**. No existe self-registration
ni aprovisionamiento automático desde sistemas externos en Fase 10.

### Flujo nominal (7 pasos)

```
[Admin]                     [Backend]                  [Usuario]
   │                            │                          │
   │ 1. POST /admin/users/invite │                          │
   │ ─────────────────────────▶ │                          │
   │                            │ AdminCreateUser (Cognito) │
   │                            │ Genera token único 72h    │
   │                            │ Registra en audit_trail   │
   │                            │ ──────────────────────▶  │
   │                            │      Email "invitation"   │
   │                            │      (ADR 0059)           │
   │                 204         │                          │
   │ ◀─────────────────────────  │                          │
   │                            │                          │
   │                            │   2. Click link email    │
   │                            │ ◀───────────────────────  │
   │                            │                          │
   │                            │  GET /onboarding/activate │
   │                            │     ?token=...           │
   │                            │ ◀───────────────────────  │
   │                            │ Valida token (72h, one-use)│
   │                            │ ──────────────────────▶  │
   │                            │   Formulario activación  │
   │                            │                          │
   │                            │  3. Set password + MFA   │
   │                            │ ◀───────────────────────  │
   │                            │ RespondToAuthChallenge    │
   │                            │ (Cognito FORCE_CHANGE_    │
   │                            │  PASSWORD)               │
   │                            │ AssociateSoftwareToken    │
   │                            │ VerifySoftwareToken       │
   │                            │ Registra activación en   │
   │                            │ audit_trail              │
   │                            │                          │
   │                            │  4. Primer login         │
   │                            │ ◀───────────────────────  │
   │                            │ Registra primer_login en │
   │                            │ audit_trail              │
   │                            │ ──────────────────────▶  │
   │                            │   Tour guiado (3 pasos)  │
```

### Detalle de cada paso

**Paso 1 — Admin invita desde /admin/users:**

- Formulario con campos: `email` (requerido), `nombre completo` (requerido),
  `rol` (viewer/operator/admin, requerido), `área de negocio` (tag opcional),
  `mensaje personalizado` (opcional, aparece en el email de invitación).
- El backend llama `AdminCreateUser` en Cognito con `MessageAction: SUPPRESS`
  y genera un token de activación único (UUID v4 + hash SHA-256, almacenado
  en la tabla `user_invitations` de la DB con expiración 72h).
- Se envía email `invitation` via SES (ADR 0059) con el link de activación.
- El evento se registra en `audit_trail` con `action_type: user.invited`,
  `actor_user_id` del admin, `target_type: user`, `target_id`: email.

**Paso 2 — Usuario recibe email y hace click:**

- Link: `https://<dominio>/onboarding/activate?token=<uuid>`
- El frontend valida el token contra el backend (`GET /onboarding/validate-token`).
- Si el token es válido y no ha expirado: muestra el formulario de activación.
- Si el token ha expirado: muestra pantalla "Este enlace ha caducado. Contacta
  con tu administrador." (No revela que el email existe en el sistema.)

**Paso 3 — Set password + MFA:**

- Formulario: nueva contraseña (confirmar 2x), QR code para TOTP.
- El frontend guía al usuario para escanear el QR con una app de autenticación
  y verificar con el primer código de 6 dígitos.
- Si el usuario no tiene smartphone o prefiere SMS: opción visible en el
  formulario para cambiar a SMS (requiere número de teléfono).
- Al completar, el token de activación se marca como `used` (no reutilizable).
- Evento `user.activated` en `audit_trail`.

**Paso 4 — Primer login:**

- Tras activación, redirect automático a `/login` con email pre-relleno.
- Primer login exitoso: evento `user.first_login` en `audit_trail`.
- Se muestra **tour guiado opcional** (3 pantallas, skippable):
  1. "Qué es lex-agents" — propósito, alcance jurídico actual (regulatorio bancario UE+ES).
  2. "Cómo hacer una consulta" — ejemplo de query, formato de respuesta, citas.
  3. "Límites importantes" — el sistema asiste, no sustituye criterio jurídico
     cualificado; caveat de validación humana (ADR 0028).
- El tour se marca como visto en el perfil del usuario; no vuelve a aparecer.

### Reinvitación (token expirado o no usado)

Si un admin quiere reinvitar a un usuario cuyo token ha expirado:

- `POST /admin/users/{user_id}/reinvite`
- El backend invalida el token anterior (marca `invalidated: true`) y genera
  uno nuevo con 72h de validez.
- Se envía email `invitation` de nuevo.
- El usuario en Cognito permanece en estado `FORCE_CHANGE_PASSWORD` —
  no se crea una cuenta nueva.
- Evento `user.reinvited` en `audit_trail`.

### Tabla de estados de usuario

| Estado                  | Descripción                                              |
|-------------------------|----------------------------------------------------------|
| `invited`               | AdminCreateUser ejecutado; token enviado por email       |
| `token_expired`         | Token de 72h expirado sin activar                        |
| `activating`            | Token clickado; flujo de set password en curso           |
| `active`                | Cuenta activada; puede hacer login                       |
| `disabled`              | Admin ha desactivado la cuenta (no puede hacer login)    |

## Alternatives considered

**Self-registration con aprobación de admin:**

- Pro: menor carga en el admin para el alta inicial.
- Con: expone la existencia de la plataforma a quien no ha sido invitado;
  inconsistente con el modelo de acceso cerrado requerido para datos jurídicos
  sensibles.
- Rechazado: el modelo admin-driven es no negociable dado el contexto bancario.

**SSO-first sin onboarding local (Azure AD desde el inicio):**

- Pro: cero fricción si Santander Identity ya está disponible.
- Con: depende de timeline externo no controlable; bloquea el MVP.
- Rechazado para Fase 10: se implementará como upgrade path según ADR 0053.

**Email link sin token (solo magic link de Cognito):**

- Pro: menos código a mantener.
- Con: Cognito magic links tienen expiración muy corta (15 minutos) y no
  permiten personalización del flujo (set MFA en el mismo step).
- Rechazado: necesitamos controlar el flujo completo de activación.

## Consequences

**Positivo:**

- Audit trail completo desde invitación hasta primer uso — trazabilidad
  requerida por DORA.
- El admin tiene visibilidad del estado de cada usuario en `/admin/users`
  (invited / expired / active / disabled).
- El tour reduce las consultas de soporte de primeros usuarios.
- La reinvitación no requiere borrar y recrear la cuenta Cognito.

**Negativo:**

- Requiere tabla `user_invitations` nueva en la DB (migration Alembic nueva).
- La ventana de 72h puede ser insuficiente para usuarios con calendarios
  muy cargados; el admin puede reinvitar sin penalización.
- El tour guiado es contenido que debe mantenerse actualizado cuando cambie
  el alcance jurídico de la plataforma.
