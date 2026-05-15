# 0059 — Email infrastructure (Amazon SES)

**Status:** Accepted  
**Date:** 2026-05-15

## Context

El onboarding flow (ADR 0055) requiere enviar emails transaccionales a los
usuarios: invitación, activación, recordatorio de token, reset de contraseña,
alertas de seguridad y notificación de desactivación de cuenta.

Actualmente la plataforma no tiene ningún sistema de envío de email. Las
notificaciones son exclusivamente in-app (tabla `notifications` en DB,
drawer en el frontend).

El sistema de email debe ser:
- Fiable en el contexto bancario (alta tasa de entrega, reputación del
  dominio protegida).
- Integrado con el audit trail existente (bounces y complaints deben
  registrarse como eventos auditables).
- Consistente con el branding de la plataforma (ADR 0057 y ADR 0058).
- Gestionado en la misma región AWS que el resto de la infraestructura
  (ADR 0036: eu-central-1 como región primaria).

## Decision

Usar **Amazon SES** (Simple Email Service) en `eu-central-1` para todos
los emails transaccionales de lex-agents.

### Configuración del dominio

- **Dominio de envío:** `lex-agents.example.com` (placeholder para Fase 10).
  En producción Santander, el equipo de IT de Santander proveerá un dominio
  aprobado (`lex-agents.gruposantander.com` o equivalente).
- **From address:** `noreply@lex-agents.example.com`
- **Display name:** `Plataforma Jurídica`
- **Reply-to:** No configurado (no se esperan respuestas; si el usuario necesita
  soporte, el email incluye un link al canal de soporte interno).

### Autenticación del dominio

Los tres mecanismos de autenticación de email se configuran obligatoriamente:

- **DKIM** (DomainKeys Identified Mail): SES genera un par de claves RSA 2048-bit;
  la clave pública se publica como registro DNS TXT en el dominio de envío.
  Protege la integridad del mensaje y el remitente.
- **SPF** (Sender Policy Framework): registro DNS TXT que autoriza a los
  servidores SES de AWS a enviar en nombre del dominio. Previene spoofing básico.
- **DMARC** (Domain-based Message Authentication): política `p=quarantine`
  para Fase 10 (los mensajes que fallen SPF y DKIM van a cuarentena, no se
  descartan aún). Transición a `p=reject` cuando el dominio tenga suficiente
  histórico de entrega limpio.

### Gestión de bounces y complaints

Emails que generan bounce o complaint llevan a la degradación de la reputación
del dominio en SES, con riesgo de ser movido a sandbox o bloqueado. Proceso:

```
SES → SNS Topic (ses-notifications) → Lambda (ses-event-processor) → audit_trail
```

- **Hard bounce**: dirección de email inválida → marcar usuario como
  `email_invalid` en DB → notificar al admin in-app → registrar en audit_trail
  con `action_type: email.hard_bounce`.
- **Soft bounce**: problema temporal → reintentar automáticamente hasta 3
  veces en 24h → si persiste, tratar como hard bounce.
- **Complaint**: usuario marcó el email como spam → desactivar envíos de email
  no-críticos a esa dirección → notificar al admin → registrar en audit_trail
  con `action_type: email.complaint`.

### Templates

Los templates se almacenan en SES (tipo `SES Email Template`) y en el
repositorio en `apps/api/src/lex_agents_api/email_templates/` como fuente
de verdad. Deployment de templates via script de CDK o Makefile target.

Todos los templates incluyen:
- Header con el logo placeholder (slot configurable via ADR 0057).
- Footer con: nombre de la plataforma, disclaimer "Este es un sistema de uso
  interno. No responder a este email.", link para reportar problemas.

| Template ID               | Asunto                                      | Trigger                           |
|---------------------------|---------------------------------------------|-----------------------------------|
| `invitation`              | Invitación a Plataforma Jurídica            | Admin invita usuario              |
| `activation_reminder`     | Tu enlace de activación caduca mañana       | 24h antes de expiración del token |
| `password_reset`          | Solicitud de reset de contraseña            | Usuario solicita reset            |
| `password_reset_confirmation` | Tu contraseña ha sido actualizada       | Reset completado                  |
| `security_alert`          | Alerta de seguridad en tu cuenta            | Ver detalle abajo                 |
| `account_disabled`        | Tu acceso a Plataforma Jurídica ha sido suspendido | Admin desactiva cuenta     |

**Template `security_alert`** se envía ante cualquiera de estos eventos:
- Primer login desde un nuevo dispositivo o IP inusual.
- MFA habilitado o deshabilitado.
- Role cambiado (el usuario recibe notificación del cambio).
- Intento de login fallido (tras el 3er intento, antes del lockout).

El contenido del alert es genérico intencionalmente: "Hemos detectado actividad
en tu cuenta. Si no fuiste tú, contacta con tu administrador." No se incluyen
detalles técnicos (IP, user-agent) en el email para evitar exposición de
información de diagnóstico.

### Región y cuotas

- **Región:** `eu-central-1` (Fráncfort). Misma región que el resto de la
  infraestructura (ADR 0036). Datos de email no salen de la UE.
- **Cuota inicial (sandbox):** 200 emails/día, 1 email/segundo. Suficiente
  para piloto inicial.
- **Salida de sandbox:** se solicita a AWS cuando el dominio tenga histórico
  limpio y el volumen justifique el upgrade. Cuotas de producción: 50.000
  emails/día por defecto, escalable.
- **Sending rate:** máximo 14 emails/segundo en producción (más que suficiente
  para los volúmenes esperados en Fase 10).

### Integración con Cognito

Para los flujos de password reset y MFA, Cognito puede enviar sus propios
emails (via SES o su sistema interno). Se configura Cognito para usar **el
mismo SES identity** que lex-agents, con los templates personalizados, en
lugar de los emails por defecto de Cognito. Esto asegura que todos los emails
al usuario tienen el mismo branding y provienen del mismo dominio.

## Alternatives considered

**SendGrid:**

- Pro: interfaz de administración excelente, analytics detallados.
- Con: vendor externo adicional fuera del ecosistema AWS; datos de email
  pasan por servidores de SendGrid (implicaciones de privacidad para emails
  internos bancarios).
- Rechazado: SES en AWS mantiene los datos dentro del perímetro de la
  infraestructura del proyecto.

**Postmark:**

- Pro: excelente reputación para emails transaccionales.
- Con: mismo problema que SendGrid (vendor externo, datos fuera de AWS).
- Rechazado por las mismas razones.

**SES en eu-west-1 (Irlanda) en lugar de eu-central-1:**

- Pro: eu-west-1 tiene historial más largo en AWS y algunas features de SES
  disponibles antes.
- Con: inconsistente con la política de región primaria (ADR 0036). Los
  emails contienen metadatos de usuarios (nombre, email) que son datos
  personales — deben procesarse en la misma región que el resto de datos.
- Rechazado: coherencia de región es prioritaria.

**Servidor SMTP self-hosted (Postfix, etc.):**

- Pro: control total, sin vendor lock-in.
- Con: gestión de reputación de dominio enormemente compleja; alta probabilidad
  de que los emails vayan a spam. Operación adicional significativa.
- Rechazado.

## Consequences

**Positivo:**

- SES dentro de AWS — los metadatos de email (destinatario, asunto) no salen
  del perímetro de la infraestructura del proyecto.
- Integración nativa con SNS/Lambda para el pipeline de bounce/complaint
  → audit trail.
- Misma región que el resto de la infraestructura: latencia mínima, costes
  de transferencia de datos = $0.
- SES es coste-efectivo: ~$0.10 por cada 1000 emails. Para el volumen
  esperado en piloto (< 500 usuarios), el coste mensual es negligible.
- Cognito puede usar el mismo SES identity, unificando el branding de todos
  los emails al usuario.

**Negativo:**

- El dominio placeholder `lex-agents.example.com` no puede enviarse a emails
  externos — en producción debe configurarse el dominio real Santander.
  Esto implica coordinación con el equipo de IT de Santander para la
  delegación DNS.
- SES sandbox limita a 200 emails/día hasta la salida de sandbox — en el
  piloto inicial esto puede ser suficiente, pero debe monitorizarse.
- Los templates en SES tienen un lenguaje de templating limitado (Handlebars
  simplificado). Personalizaciones complejas requieren generar el HTML
  completo desde el backend antes de enviarlo (sin usar templates SES).
- La cadena SNS → Lambda → audit_trail añade un componente operativo adicional
  que debe monitorizarse (alertas si la Lambda falla y no procesa bounces).
