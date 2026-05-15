# 0053 — Modelo de identidad: Cognito sin signup público

**Status:** Accepted  
**Date:** 2026-05-15

## Context

Hasta Fase 9, la identidad de la aplicación se gestiona mediante JWT HS256
con usuarios almacenados en la variable de entorno `AUTH_USERS_JSON` (array
JSON con contraseñas hasheadas con bcrypt). Este sistema es suficiente para
un equipo de desarrollo reducido, pero no cumple los requisitos de una
plataforma bancaria en producción:

- No soporta MFA ni lockout de cuentas.
- Los usuarios son un secreto de infraestructura, no un recurso gestionable.
- No hay mecanismo de invitación, reset de contraseña ni auditoría de sesiones.
- No existe upgrade path hacia federación corporativa (Azure AD Santander).

La plataforma utiliza ya IAM Identity Center (`infra/cdk/lib/stacks/identity-center.ts`)
para acceso humano a la consola AWS. Ese sistema no es el IdP de la aplicación —
los usuarios de AWS y los usuarios de lex-agents son poblaciones distintas.

DORA Artículo 9.2 exige autenticación multifactor y gestión centralizada de
identidades para sistemas ICT de entidades financieras significativas.

## Decision

Adoptar **Amazon Cognito User Pool** como sistema de identidad de la aplicación
lex-agents, con las siguientes restricciones de configuración:

### Signup

- Signup público: **DESHABILITADO**. No existe endpoint de autoregistro.
- Único flujo de alta: admin invita explícitamente (ver ADR 0055).
- `AllowAdminCreateUserOnly: true` en la configuración del User Pool.

### MFA

- MFA obligatorio para todos los usuarios.
- Método por defecto: **TOTP** (Google Authenticator, Authy, etc.).
- Método fallback: SMS (opcional; requiere número de teléfono en perfil).
- MFA se configura en el primer login tras activación de cuenta.

### Política de contraseñas

- Longitud mínima: 14 caracteres.
- Requiere mayúsculas, minúsculas, números y símbolos.
- No reúso de las últimas 12 contraseñas.
- Temporal passwords (generadas por admin) tienen expiración de 72 horas.

### Lockout

- Bloqueo de cuenta tras 5 intentos fallidos consecutivos.
- Desbloqueo: manual por admin o automático tras 30 minutos.

### Tokens

| Token       | Duración | Notas                                 |
|-------------|----------|---------------------------------------|
| ID token    | 1 hora   | Contiene claims de identidad y grupos |
| Access token| 1 hora   | Usado para llamadas a APIs protegidas |
| Refresh token | 30 días | Rotación activada; invalida el anterior en cada uso |

### Hosted UI

La Hosted UI de Cognito **no se utiliza**. El flujo de login pasa íntegramente
por el frontend Next.js de lex-agents para mantener consistencia de branding
(ver ADR 0057). Cognito actúa como backend de identidad a través del SDK de
Amplify o las APIs de Cognito directamente desde el frontend.

### Separación de sistemas de identidad

```
Cognito User Pool          IAM Identity Center
───────────────────        ───────────────────
Usuarios de la app         Ingenieros / ops con
lex-agents                 acceso a consola AWS

Autenticación de           Permission sets para
consultas jurídicas        recursos AWS
                           (ya implementado en
                           ADR 0046)
```

Ambos sistemas coexisten. Un usuario puede estar en ambos con la misma
dirección email, pero son cuentas independientes.

### Upgrade path: federación Azure AD Santander

Cuando Santander Identity esté disponible para integración:

1. Se añade Azure AD como **IdP federado** en el mismo User Pool existente
   (SAML 2.0 o OIDC, según lo que exponga el equipo de identidad de Santander).
2. Las cuentas existentes creadas por invitación continúan funcionando sin
   modificación.
3. Nuevos usuarios corporativos pueden autenticarse via SSO sin crear cuenta
   local.
4. Matching de cuentas: misma dirección email = misma cuenta interna en
   lex-agents. El atributo `email` es el identificador de identidad.
5. La transición es transparente para el backend — el JWT sigue llegando con
   los mismos claims (`cognito:groups`, `email`, `sub`).

Este upgrade path no requiere cambios de arquitectura en Fase 10; se ejecutará
en una sub-fase futura cuando Santander Identity esté disponible.

## Alternatives considered

**Auth0 / Okta:**

- Pro: producto maduro con UI de administración excelente.
- Con: vendor externo adicional, costes por MAU, datos de identidad fuera
  de la infraestructura AWS del proyecto, complejidad de integración con
  IAM Identity Center para los links federados de ADR 0056.
- Rechazado: el ecosistema AWS (Cognito + IAM IC) es más coherente con la
  arquitectura existente y más alineado con los requisitos de residencia de
  datos (ADR 0036).

**Azure AD directo (sin Cognito):**

- Pro: identidad corporativa Santander desde el primer día.
- Con: depende de aprobación y timeline del equipo de identidad Santander
  (no controlable); bloquea el MVP.
- Rechazado para Fase 10: Cognito con upgrade path Azure AD es la secuencia
  correcta.

**Keycloak self-hosted:**

- Pro: control total, sin vendor lock-in.
- Con: operación de un sistema de identidad crítico requiere expertise
  dedicado; adds operational burden significativo.
- Rechazado: la plataforma ya está all-in en AWS; Cognito es la opción
  managed equivalente.

## Consequences

**Positivo:**

- MFA y lockout cumplen DORA Art. 9.2 desde el primer deploy en producción.
- Gestión de usuarios via AWS Console o API (AdminCreateUser, AdminDeleteUser,
  AdminAddUserToGroup) — no es necesario SSH a un servidor.
- Audit de sesiones disponible via CloudTrail para el User Pool.
- Upgrade path a Azure AD documentado y técnicamente viable sin refactoring.
- Tokens JWT estándar (OIDC) verificables con JWKS endpoint público del
  User Pool — compatible con Grafana, Langfuse, oauth2-proxy (ADR 0056).

**Negativo:**

- El backend actual (`apps/api/src/lex_agents_api/auth.py`) debe reescribirse
  para verificar tokens Cognito contra el JWKS endpoint en lugar del secret
  simétrico HS256 actual. Trabajo acotado a la capa de auth.
- `AUTH_USERS_JSON` env var se depreca. Requiere migración de usuarios
  existentes (ver ADR 0054).
- Cognito tiene límites de throughput en operaciones de autenticación
  (Default: 120 req/s para USER_POOLS flow). Más que suficiente para el
  tamaño del piloto Santander.

**Deuda técnica resuelta:**

- Elimina la gestión de usuarios como secreto de infraestructura.
- Elimina el JWT secret simétrico compartido.
- Elimina `scripts/admin_bootstrap.py` como única herramienta de gestión
  de usuarios.
