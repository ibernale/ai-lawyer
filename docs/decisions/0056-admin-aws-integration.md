# 0056 — Integración AWS en admin: iframe SSO vs links federados

**Status:** Accepted  
**Date:** 2026-05-15

## Context

El admin panel actual (`apps/web/src/app/admin/`) expone tres secciones:
Ops Center, Governance y Audit Trail. Todas las herramientas de observabilidad
y operación AWS (Grafana, Langfuse, Jaeger, CloudWatch, X-Ray, Step Functions,
Bedrock) son accesibles solo abriendo URLs separadas o la consola AWS.

Esto crea fricción operativa: el operador debe mantener múltiples pestañas,
gestionar sesiones separadas y cambiar de contexto constantemente.

El objetivo de Fase 10 es presentar una **admin unificada** donde el operador
acceda a todas las herramientas relevantes desde un único punto de entrada
autenticado. La solución técnica varía según si la herramienta soporta
embedding en iframe o no.

IAM Identity Center ya está implementado en
`infra/cdk/lib/stacks/identity-center.ts` con los permission sets
AdministratorAccess, DeveloperAccess, DataAnalystAccess y SecurityAuditAccess.
Cognito es el sistema de identidad de la aplicación (ADR 0053).

## Decision

Dos patrones según la capacidad técnica de cada herramienta:

### Patrón A — Iframe embebido con SSO (herramientas self-hosted)

Las herramientas self-hosted soportan autenticación delegada y no bloquean
embedding en iframes. El usuario ve la herramienta dentro del admin panel
sin cambio de contexto visual.

**Implementación por herramienta:**

**Grafana:**
- JWT auth activado: Grafana verifica tokens contra el JWKS endpoint de
  Cognito (`https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json`).
- El reverse proxy (nginx o ALB) inyecta header `X-JWT-Assertion` con el
  JWT de la sesión activa del usuario.
- El iframe apunta a la URL del dashboard con parámetro `?kiosk` para
  ocultar la navegación de Grafana.
- El role Cognito del usuario determina qué dashboards son visibles
  (Grafana Teams mapeados a grupos Cognito).

**Langfuse:**
- Configurado con Cognito como OIDC provider.
- Langfuse soporta OIDC nativo desde v2.0 — se configura `NEXTAUTH_URL`,
  `AUTH_COGNITO_CLIENT_ID` y `AUTH_COGNITO_CLIENT_SECRET`.
- Iframe directo; Langfuse gestiona su propio estado de sesión.

**Jaeger:**
- Jaeger UI no tiene auth propio. Se despliega detrás de
  **oauth2-proxy** configurado con Cognito como provider OIDC.
- oauth2-proxy valida el cookie de sesión contra Cognito; si no existe,
  redirige a Cognito login (transparente para el usuario ya autenticado
  en lex-agents porque comparten el mismo User Pool).
- Iframe apunta al endpoint de oauth2-proxy.

**Dagster (si se mantiene self-hosted):**
- Mismo patrón que Jaeger: oauth2-proxy delante de Dagster UI.
- Si Dagster migra a Step Functions (ADR 0047), este ítem queda obsoleto.

### Patrón B — Link federado a consola AWS (servicios AWS-nativos)

AWS bloquea embedding de la consola AWS en iframes mediante la cabecera
`X-Frame-Options: SAMEORIGIN` en todas las páginas de la consola. No es
posible embeber CloudWatch, X-Ray, Step Functions ni Bedrock en un iframe
sin técnicas de rewriting que son frágiles y rompen con cada release de AWS.

**Por qué no reverse proxy para CloudWatch:**

La consola AWS incluye `X-Frame-Options: SAMEORIGIN` y
`Content-Security-Policy: frame-ancestors 'self'` explícitamente para
prevenir clickjacking. Intentar reescribir estas cabeceras con un proxy
requiere interceptar y modificar el HTML de cada respuesta, lo que:
1. Rompe con cada actualización de la consola AWS (múltiples veces al mes).
2. Puede invalidar controles de seguridad de AWS, generando riesgo de
   cumplimiento.
3. Viola los términos de servicio de AWS.

La alternativa soportada oficialmente es la **federación de consola AWS**:
generación de URLs de signin temporales que autentican al usuario en la
consola directamente.

**Implementación del Patrón B:**

1. **SCIM provisioning Cognito → IAM Identity Center:**
   - Se activa sincronización automática de usuarios y grupos de Cognito
     hacia IAM Identity Center via SCIM endpoint.
   - Cuando un admin añade un usuario al grupo `operator` en Cognito,
     IAM Identity Center recibe el evento y asigna el permission set
     correspondiente al usuario.
   - Mapping de grupos a permission sets:

     | Grupo Cognito | Permission set IAM IC     |
     |---------------|---------------------------|
     | `viewer`      | SecurityAuditAccess       |
     | `operator`    | DataAnalystAccess         |
     | `admin`       | DeveloperAccess           |

2. **Generación de signin URLs:**
   - Cuando el usuario hace click en "Ver en CloudWatch" (o cualquier
     herramienta de Patrón B), el frontend llama al backend:
     `POST /admin/aws/signin-url` con el target dashboard como parámetro.
   - El backend asume el IAM role correspondiente al grupo Cognito del
     usuario (sts:AssumeRoleWithWebIdentity) y genera una URL de signin
     federado temporalmente válida (~15 minutos).
   - El frontend abre la URL en una **nueva pestaña**.
   - En visitas subsiguientes, IAM Identity Center mantiene la sesión
     activa y no requiere interacción adicional del usuario.

3. **Política de mínimo privilegio:**
   - `viewer` → `SecurityAuditAccess`: solo lectura de logs y métricas,
     sin acceso a datos en reposo ni configuración.
   - `operator` → `DataAnalystAccess`: lectura de CloudWatch, X-Ray,
     Step Functions executions, Bedrock invocation logs.
   - `admin` → `DeveloperAccess`: scope más amplio, pero sin
     `AdministratorAccess` — los cambios de infraestructura siguen
     siendo exclusivos del pipeline CI/CD (ADR 0046).

### Tabla resumen por herramienta

| Herramienta               | Patrón | Mecanismo de auth         | Presentación en UI        |
|---------------------------|--------|---------------------------|---------------------------|
| Grafana                   | A      | JWT → JWKS Cognito        | Iframe con `?kiosk`       |
| Langfuse                  | A      | OIDC con Cognito          | Iframe directo            |
| Jaeger                    | A      | oauth2-proxy + Cognito    | Iframe via proxy          |
| Dagster UI (si self-hosted)| A     | oauth2-proxy + Cognito    | Iframe via proxy          |
| CloudWatch dashboards     | B      | IAM IC federation         | Nueva pestaña             |
| X-Ray ServiceLens         | B      | IAM IC federation         | Nueva pestaña             |
| AgentCore Observability   | B      | IAM IC federation         | Nueva pestaña             |
| Step Functions executions | B      | IAM IC federation         | Nueva pestaña             |
| Bedrock invocation logs   | B      | IAM IC federation         | Nueva pestaña             |

### UX del Patrón B

Las herramientas de Patrón B se presentan en el admin panel como tarjetas con
un botón "Abrir en AWS →" que indica visualmente que se abrirá una nueva
pestaña. Se incluye un tooltip: "Se abre en la consola AWS autenticada con tus
credenciales."

La primera vez que el usuario navega a una herramienta de Patrón B puede ver
el prompt de IAM Identity Center (~2 segundos). Las visitas subsiguientes en
la misma sesión son inmediatas.

## Alternatives considered

**Reverse proxy para CloudWatch con rewriting de cabeceras:**

- Pro: experiencia completamente unificada en el iframe.
- Con: frágil (rompe con cada release AWS), viola X-Frame-Options y TOS de AWS.
- Rechazado: no es mantenible ni conforme.

**Un único proxy de autenticación para todas las herramientas (oauth2-proxy global):**

- Pro: un solo componente de auth para todo.
- Con: las herramientas con auth OIDC nativo (Langfuse) o JWT nativo (Grafana)
  tienen mejor soporte con su propio mecanismo; el proxy global introduce un
  punto de fallo adicional.
- Rechazado: enfoque tool-by-tool es más robusto y aprovecha capacidades nativas.

**AWS Single Sign-On App Assignments para herramientas self-hosted:**

- Pro: unifica toda la auth en IAM Identity Center.
- Con: requiere que las herramientas self-hosted sean accesibles desde internet
  o estén en la misma VPC que el Identity Center endpoint, añadiendo complejidad
  de red.
- Rechazado para Fase 10; puede evaluarse en H3.

## Consequences

**Positivo:**

- El operador tiene una vista centralizada de todas las herramientas operativas
  sin necesidad de gestionar sesiones separadas para las herramientas de Patrón A.
- SCIM entre Cognito e IAM Identity Center mantiene los permisos AWS
  sincronizados automáticamente cuando cambia el role de un usuario.
- Mínimo privilegio enforced: un operator no puede asumir AdministratorAccess
  en AWS aunque lo intente manualmente.
- Cumple DORA Art. 9.4 (acceso basado en roles, principio de mínimo privilegio).

**Negativo:**

- Las herramientas de Patrón B abren nueva pestaña — la experiencia no es
  completamente unificada. Es un compromiso consciente y documentado.
- SCIM provisioning tiene latencia (segundos a minutos); un cambio de role
  puede no reflejarse instantáneamente en IAM Identity Center.
- Requiere configuración de SCIM en IAM Identity Center y en Cognito User Pool
  (nuevo recurso CDK).
- La generación de signin URLs requiere un endpoint backend adicional con
  permisos sts:AssumeRoleWithWebIdentity, que debe estar correctamente
  acotado por IAM.
