# Roadmap Fase 10 — lex-agents

**Versión de partida:** v0.5.0 (Fase 9 complete — banking-grade AWS dev)
**Objetivo Fase 10:** Plataforma en producción con primer tenant Santander real.

---

## Resumen ejecutivo

Fase 10 toma la infraestructura banking-grade de Fase 9 y la lleva a
producción. Las iniciativas se agrupan en tres horizontes:

- **H1 (0–3 meses):** Habilitadores técnicos sin los cuales producción es inviable
- **H2 (3–6 meses):** Capacidades de negocio que multiplican el valor
- **H3 (6–12 meses):** Escala, soberanía y multi-tenencia

---

## Iniciativas

### 1. Integración SSO Santander (H1 — P1)

**Descripción:** Federar IAM Identity Center con Azure AD corporativo Santander
vía SCIM + SAML 2.0, eliminando la gestión manual de usuarios en IAM Identity
Center.

**Motivación:** DORA Art. 9.2 requiere MFA y gestión centralizada de identidades.
El equipo de Santander usa Azure AD; crear usuarios duplicados introduce riesgo
de desincronización y de cuentas huérfanas.

**Dependencias:** Aprobación del equipo de IAM corporativo Santander. SLA de
Azure AD B2B/SCIM con equipo de plataforma.

**Esfuerzo estimado:** 2–3 semanas (infra CDK + validación equipo IAM)
**Coste incremental:** ~$0 (IAM Identity Center no cobra por usuarios SCIM)

**Pasos:**

1. Habilitar SCIM provisioning en IAM Identity Center (management account)
2. Configurar app enterprise en Azure AD con SCIM endpoint
3. Sincronizar grupos Azure AD → IAM IC groups (admins, developers, etc.)
4. Configurar SAML 2.0 federation: Azure AD como IdP
5. Validar login end-to-end con cuenta Santander real
6. Deprecar usuarios manuales en IAM IC

---

### 2. Despliegue workloads-pre con app real (H1 — P1)

**Descripción:** Activar `AppServicesStack`, `PipelinesStack`, `LangfuseStack`
y `ObservabilityStack` en la cuenta `workloads-pre` (provisionada en Fase 9.5 sin app).

**Motivación:** Pre es el último gate antes de producción. Santander necesita
validar el comportamiento end-to-end con datos reales antes de dar luz verde a pro.

**Dependencias:**

- SSO Santander (#1) debe estar completo (usuarios reales para login)
- Datos de prueba no-producción aprobados por DPO
- ACM certificate en eu-central-1 para dominio pre (`lex-agents-pre.santander.internal`)

**Esfuerzo estimado:** 1–2 semanas
**Coste incremental:** ~$600/mes (workloads-pre completo activo)

---

### 3. Reserved Capacity Bedrock (H2 — P1)

**Descripción:** Activar Provisioned Throughput de Bedrock para modelos Claude
Sonnet y Haiku en eu-central-1 tras 1 mes de datos de uso reales.

**Motivación:** ADR 0045 estimó ~$390/mes en inferencia LLM con on-demand. Con
1 mes de datos de uso (RCU/día promedio), Reserved Capacity puede reducir el coste
de inferencia ~30–40%.

**Dependencias:** 1 mes de datos reales de producción. No activar antes: sin datos
se puede sobre- o infra-dimensionar la capacidad.

**Esfuerzo estimado:** 1 semana (CDK + análisis de datos)
**Coste incremental:** Ahorro estimado ~$100–150/mes neto

---

### 4. TLPT — Threat-Led Penetration Testing (H2 — P1)

**Descripción:** Preparación y ejecución del primer TLPT (Threat-Led Penetration
Testing) conforme a DORA Art. 26. TLPT es obligatorio para entidades
financieras significativas que usen ICT de terceros críticos.

**Motivación:** DORA Art. 26 obliga a TLPT antes de que lex-agents gestione
datos productivos de clientes. Sin TLPT aprobado, el despliegue en producción
real puede no ser autorizable por el supervisor bancario (BCE/Banco de España).

**Dependencias:**

- workloads-pre activo con app real (#2)
- Contratación de un "red team" certificado TIBER-EU
- Aprobación del CISO de Santander
- Coordinación con proveedor cloud (AWS) per DORA Art. 26.7

**Esfuerzo estimado:** 3–4 meses (incluyendo preparación, ejercicio, remediación)
**Coste incremental:** Externo — coste red team TIBER-EU (~€50k–100k, presupuesto Santander)

---

### 5. Despliegue Madrid eu-south-2 (H2 — P2)

**Descripción:** Evaluar y, si AgentCore + Bedrock están disponibles en
`eu-south-2` (Madrid), desplegar workloads-pro en región española.

**Motivación:** Requisitos de residencia de datos de clientes españoles.
DORA Art. 36 y GDPR pueden exigir que los datos no salgan de España para
ciertos tipos de datos. eu-south-2 es la región AWS de Madrid (disponible
desde 2022 pero con servicios limitados aún).

**Dependencias:** AWS anuncia soporte de Bedrock + Bedrock Knowledge Bases en
eu-south-2 (pendiente en 2026). Verificar disponibilidad antes de iniciar.

**Esfuerzo estimado:** 3–4 semanas si los servicios están disponibles
**Coste incremental:** ~$200/mes (region adicional estándar)

---

### 6. Pilot Light DR (H2 — P2)

**Descripción:** Elevar la estrategia de DR de Backup-Restore (ADR 0051,
RTO 8h) a Pilot Light (RTO 2h) desplegando infraestructura mínima permanente
en eu-west-1 (Aurora read replica + ECS cluster vacío).

**Motivación:** DORA Art. 11.3 fija el RTO objetivo para entidades
significativas en ≤ 4h en staging. Con Backup-Restore el RTO dev es 8h,
lo que no cumplirá el requisito de producción. Pilot Light reduce RTO a ~2h
sin el coste de Active-Active (~3× más caro).

**Dependencias:** workloads-pro activo (#2 → producción). No tiene sentido
en dev; el coste no está justificado.

**Esfuerzo estimado:** 2–3 semanas (CDK NetworkSpokeStack + DataStack DR region)
**Coste incremental:** ~$180/mes (Aurora replica + ECS cluster vacío eu-west-1)

---

### 7. Multi-tenencia para filiales Santander Group (H3 — P2)

**Descripción:** Extender lex-agents para servir múltiples entidades del Grupo
Santander (Openbank, Santander Consumer Finance, Santander UK...) con
aislamiento de datos garantizado a nivel de Aurora schema o cuenta AWS.

**Motivación:** Si Santander valida lex-agents en Spain retail, la expansión
natural es otras entidades del Grupo. Multi-tenancy multiplica el ROI de la
plataforma sin multiplicar el coste.

**Dependencias:**

- Producción España estable (>3 meses)
- Evaluación legal cross-border (datos UK post-Brexit vs GDPR EU)
- Arquitectura tenant isolation: schema-per-tenant (simple) vs account-per-tenant
  (más aislamiento, más coste)

**Esfuerzo estimado:** 6–8 semanas (diseño + CDK + migración datos)
**Coste incremental:** ~$300–500/mes por tenant adicional (Aurora, ECS, Bedrock)

---

### 8. Integración DMS Santander (H3 — P2)

**Descripción:** Conectar lex-agents a los Document Management Systems
corporativos de Santander (SharePoint Online, iManage Work) para ingestar
contratos y documentos internos directamente, sin upload manual.

**Motivación:** El caso de uso productivo real de lex-agents no es
documentos públicos (BOE/EUR-Lex), sino documentos internos: contratos de
externalización, policy documents, regulación interna. Sin acceso al DMS,
el valor es limitado.

**Dependencias:**

- APIs DMS habilitadas para uso externo (requiere aprobación IT Santander)
- Clasificación de datos: los documentos del DMS pueden contener datos de clientes
  (requiere DPA y controles GDPR adicionales)

**Esfuerzo estimado:** 4–6 semanas
**Coste incremental:** ~$50/mes (Lambda ingest + S3 docs)

---

### 9. Licencias comerciales (H3 — P2)

**Descripción:** Activar integración con bases de datos jurídicas comerciales:
Aranzadi (Thomson Reuters), La Ley (Wolters Kluwer), Tirant lo Blanch.

**Motivación:** Las fuentes open (BOE, EUR-Lex, CENDOJ) son necesarias pero no
suficientes para análisis jurídico bancario profundo. La doctrina, los
comentarios de autores y la jurisprudencia sistematizada de estas editoriales
mejoran significativamente la calidad de las respuestas.

**Dependencias:**

- Contratación de licencias API (presupuesto legal Santander)
- Negociación de condiciones de uso con las editoriales (IA y análisis está
  sujeto a condiciones especiales en algunos contratos)

**Esfuerzo estimado:** 2–3 semanas técnicas (source adapter + pipeline) + tiempo
de negociación comercial (variable)
**Coste incremental:** Licencias APIs — variable (€15k–50k/año según editorial)

---

### 10. Autorización formal CENDOJ / CGPJ (H1/H2 — P1)

**Descripción:** Tramitar la autorización formal del Consejo General del Poder
Judicial (CGPJ) para el acceso programático a CENDOJ con cuota elevada.

**Motivación:** Actualmente lex-agents accede a CENDOJ en modo público
(límite 50 req/día, ADR 0049). Para producción real en banca necesitamos acceso
con cuota mayor y acuerdo formal. El CGPJ tiene un programa de colaboración
institucional con entidades del sector financiero.

**Dependencias:**

- Carta de presentación de Santander como entidad financiera regulada
- Identificación del interlocutor en CGPJ (área de Nuevas Tecnologías)
- Potencialmente: DPA entre Santander y CGPJ para datos de jurisprudencia

**Esfuerzo estimado:** 1 semana técnica + 2–4 meses tramitación CGPJ
**Coste incremental:** ~$0 (CENDOJ es gratuito; solo cambia la cuota)

---

## Resumen de prioridades y horizonte

| #   | Iniciativa                 | Prioridad | Horizonte | Dependencia crítica              |
| --- | -------------------------- | --------- | --------- | -------------------------------- |
| 1   | SSO Santander (Azure AD)   | P1        | H1        | Aprobación IAM Santander         |
| 2   | workloads-pre con app real | P1        | H1        | SSO (#1) + DPO sign-off          |
| 3   | Reserved Capacity Bedrock  | P1        | H2        | 1 mes datos producción           |
| 4   | TLPT                       | P1        | H2        | workloads-pre (#2) + CISO        |
| 10  | Autorización CENDOJ/CGPJ   | P1        | H1/H2     | Tramitación administrativa       |
| 5   | Madrid eu-south-2          | P2        | H2        | Disponibilidad Bedrock en región |
| 6   | Pilot Light DR             | P2        | H2        | workloads-pro activo             |
| 7   | Multi-tenencia             | P2        | H3        | Producción estable >3 meses      |
| 8   | Integración DMS Santander  | P2        | H3        | APIs DMS habilitadas             |
| 9   | Licencias comerciales      | P2        | H3        | Presupuesto editorial            |

---

## Proyección de coste Fase 10 (baseline)

| Escenario                           | Coste/mes estimado    |
| ----------------------------------- | --------------------- |
| Fase 9.5 (dev solo)                 | ~$1.350               |
| + workloads-pre con app (H1)        | ~$1.950               |
| + Reserved Capacity Bedrock (H2)    | ~$1.800 (ahorro neto) |
| + Pilot Light DR eu-west-1 (H2)     | ~$1.980               |
| + workloads-pro (producción, H2/H3) | ~$3.500–4.000         |

_Proyecciones sujetas a revisión tras 1 mes de datos reales de uso._
_Ver `docs/aws/cost-model.md` para el modelo detallado._

---

_Documento creado: 2026-05-14 — Fase 9.5 release_
_Próxima revisión: 2026-08-14 (fin H1)_
