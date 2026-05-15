# Roadmap Fase 11

**Estado:** Planificación  
**Horizonte estimado:** Q3-Q4 2026  
**Dependencia:** Fase 10 completa y en producción estable

---

## Resumen ejecutivo

La Fase 11 consolida Lex Agents como plataforma empresarial lista para despliegue a escala en Santander. Los cinco bloques temáticos abordan identidad corporativa, internacionalización, cumplimiento legal, robustez de infraestructura y capacidades avanzadas de IA.

---

## Bloque 1: Identidad Corporativa

**Objetivo:** Integrar Lex Agents con el ecosistema de identidad corporativa de Santander.

### Funcionalidades

- **Cognito IdP con SSO corporativo:** Integración con Active Directory corporativo mediante SAML 2.0 / OIDC. Los usuarios se autentican con sus credenciales de red Santander, eliminando la gestión de contraseñas locales.
- **MFA obligatorio:** Autenticación multifactor requerida para todos los roles. Soporte para TOTP (authenticator app) y SMS.
- **Política de contraseñas:** Aplicación de la política corporativa de Santander (longitud mínima, complejidad, rotación periódica) para cuentas de servicio y usuarios locales residuales.
- **Gestión de grupos en AD:** Los roles de Lex Agents (`viewer`, `operator`, `admin`) se mapean a grupos de AD para simplificar el alta/baja de usuarios.

**Impacto:** Elimina el fichero `AUTH_USERS_JSON` como fuente de verdad. El onboarding de nuevos usuarios pasa de 2 días a minutos.

---

## Bloque 2: Multi-idioma / Multi-tenant

**Objetivo:** Habilitar el uso de la plataforma en múltiples países y unidades de negocio.

### Funcionalidades

- **i18n ES/EN/PT:** Internacionalización completa de la interfaz de usuario en español, inglés y portugués. Detección automática del idioma del navegador con opción de cambio manual.
- **Aislamiento por unidad de negocio:** Arquitectura multi-tenant donde cada unidad de negocio (Retail, CIB, WM, etc.) dispone de su propio espacio con datos aislados. Consultas de una unidad no son visibles desde otra.
- **White-label theming:** Capacidad de aplicar la identidad visual específica de cada unidad de negocio o país manteniendo la base técnica común. Configuración de logos, colores y nombre de la plataforma por tenant.

**Impacto:** Habilita el despliegue en Portugal, Reino Unido y otras geografías Santander.

---

## Bloque 3: Legal / Compliance

**Objetivo:** Cumplir con los requisitos regulatorios aplicables a la plataforma.

### Funcionalidades

- **Retención GDPR con purga automática:** Política de retención de datos configurable por tipo de dato. Purga automática al vencer el período de retención, con registro de la eliminación en el Audit Trail.
- **Firmas eIDAS:** Soporte para firma electrónica cualificada (eIDAS) en documentos generados por la plataforma que requieran validez legal.
- **Reporting DORA:** Generación automática de los informes de resiliencia operativa requeridos por el Reglamento DORA (Digital Operational Resilience Act). Exportación en los formatos requeridos por el regulador.

**Impacto:** Reduce el trabajo manual de cumplimiento y mitiga riesgos regulatorios.

---

## Bloque 4: Infraestructura

**Objetivo:** Garantizar alta disponibilidad y resiliencia ante fallos.

### Funcionalidades

- **Aurora Global Cluster (DR):** Base de datos Aurora configurada como clúster global activo-pasivo entre dos regiones AWS. RTO < 1 minuto ante fallo regional.
- **CDK Pipeline blue/green:** Pipeline de despliegue con estrategia blue/green, eliminando el downtime en los despliegues. Rollback automático si los health checks fallan.
- **Alertas Grafana para SLOs:** Definición formal de SLOs (disponibilidad 99.9%, latencia p95 < 2s) con alertas automáticas en Grafana cuando los SLOs están en riesgo. Integración con PagerDuty para escalada.

**Impacto:** Cumple con los requisitos de disponibilidad para sistemas críticos de Santander.

---

## Bloque 5: IA Avanzado

**Objetivo:** Mejorar la calidad y cobertura de las respuestas jurídicas.

### Funcionalidades

- **Fine-tuning para banca española:** Entrenamiento específico con corpus de regulación bancaria española y documentación interna (anonimizada). Mejora la precisión en terminología específica del sector.
- **Pipeline RAGAS en CI:** Integración del framework RAGAS (Retrieval-Augmented Generation Assessment) en el pipeline de CI para evaluar automáticamente la calidad de las respuestas ante cada cambio. Los PRs que degraden las métricas de calidad son bloqueados.
- **Mejoras comparativo multi-jurisdicción:** Ampliación de la cobertura a nuevas jurisdicciones (UK, LATAM). Mejor estructuración de las respuestas comparativas con tablas y resúmenes ejecutivos.

**Impacto:** Aumenta la confianza de los usuarios en las respuestas y reduce el tiempo de validación jurídica.

---

## Dependencias y prerequisitos

| Bloque                | Prerequisito                                                                   |
| --------------------- | ------------------------------------------------------------------------------ |
| Identidad corporativa | Acceso al AD corporativo Santander, acuerdo con equipo IAM                     |
| Multi-tenant          | Decisión arquitectónica sobre modelo de aislamiento (DB por tenant vs. schema) |
| Legal/Compliance      | DPO sign-off en la política de retención GDPR                                  |
| Infraestructura       | Aprobación de costes del clúster Aurora global                                 |
| IA Avanzado           | Acuerdo legal para uso de documentación interna en fine-tuning                 |

---

## Criterios de éxito de Fase 11

- Login SSO funcionando para el 100% de los usuarios activos.
- Plataforma desplegada en al menos 2 países.
- RAGAS score > 0.85 mantenido en CI.
- Cero downtime en despliegues (blue/green).
- Reporting DORA automatizado y validado por Cumplimiento.

---

_Roadmap sujeto a revisión trimestral. Prioridades pueden ajustarse según decisiones de negocio._
