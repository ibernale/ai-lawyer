# ADR 0036 — Estrategia de regiones AWS y residencia de datos

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0001 (stack), 0005 (observabilidad), 0037, 0038, 0039, 0040, 0041, 0042, 0043, 0044  
**Sub-fases afectadas:** 9.1 – 9.5

---

## Contexto

lex-agents pasa de docker-compose local a un despliegue AWS en entorno bancario.
Dos restricciones duras condicionan cualquier decisión de región:

1. **Residencia de datos EEA** (RGPD + directrices BdE/BCE para entidades financieras):
   los datos de clientes —prompts, respuestas jurídicas, audit trail, vectores— no pueden
   salir del Espacio Económico Europeo en ningún momento del ciclo de vida.

2. **DORA Artículo 9 y 11** (Reglamento UE 2022/2554): exige control de ubicación de los
   datos ICT críticos y plan de recuperación ante desastres con región secundaria separada
   geográficamente.

Además, la selección de región primaria debe soportar en GA todos los servicios AWS AI
adoptados: AgentCore Runtime, Bedrock con modelos Claude completos, Aurora Serverless v2,
y SageMaker Inference Endpoints serverless.

---

## Decisión

### Región primaria: `eu-central-1` (Frankfurt)

Frankfurt es la elección por defecto para servicios financieros en la UE por parte de AWS.
Justificación específica para lex-agents:

- **AgentCore:** GA confirmado en eu-central-1.
- **Bedrock:** Claude Opus 4.7, Sonnet 4.6 y Haiku 4.5 disponibles en eu-central-1.
- **Aurora Serverless v2 + pgvector:** disponible en eu-central-1.
- **SageMaker Inference Endpoints serverless:** disponible en eu-central-1.
- **Latencia desde España:** ~20 ms, adecuada para consultas jurídicas (respuesta en
  segundos, no milisegundos).
- **Historial de fiabilidad:** eu-central-1 tiene el mejor SLA histórico de regiones EU.
- **Infraestructura bancaria:** múltiples entidades financieras EU operan workloads
  críticos desde eu-central-1, lo que facilita auditorías y due-diligence.

### Región secundaria: `eu-west-1` (Irlanda) — Fase 9

Frankfurt + Irlanda es la combinación estándar para DR en banca europea:

- Ambas regiones soportan AgentCore en GA.
- Alta interoperabilidad AWS (Transit Gateway cross-region, S3 replication, Aurora
  Global Database).
- Separación geográfica suficiente para DORA art. 11 (>500 km).
- Infraestructura madura; no hay riesgo de disponibilidad de servicios.

### Alternativa evaluada: Frankfurt + Madrid (`eu-south-2`)

| Criterio                      | Frankfurt + Irlanda | Frankfurt + Madrid              |
| ----------------------------- | ------------------- | ------------------------------- |
| AgentCore GA                  | ✅ Ambas            | ⚠️ Madrid: verificar en Fase 10 |
| Latencia desde sede Santander | Irlanda ~30 ms      | Madrid ~5 ms                    |
| Coste DR                      | Similar             | Similar                         |
| Riesgo disponibilidad         | Bajo                | Medio (región más nueva)        |
| Data residency España         | EEA                 | EEA + ES                        |

**Decisión:** Frankfurt + Irlanda en Fase 9.
Madrid (`eu-south-2`) se evalúa en Fase 10 una vez confirmado AgentCore GA en eu-south-2.
La ventaja de latencia desde sede Santander Madrid justifica la evaluación, pero no a
expensas del riesgo de disponibilidad de servicios AI en región más nueva.

### AWS European Sovereign Cloud: NO en Fase 9

La AWS European Sovereign Cloud (ESC) proporciona aislamiento adicional de datos y
operación por personal europeo. Se descarta para Fase 9 por:

- **Servicios disponibles limitados:** AgentCore y Bedrock con Claude no están disponibles
  en ESC. Los modelos Bedrock en ESC se limitan a modelos open-weight; Claude requiere
  región comercial.
- **Coste superior:** overhead operacional de ESC implica +20-40% sobre precio comercial.
- **Latencia de desarrollo:** penaliza el ciclo dev/test.
- **Desproporcionado para MVP:** ESC es para workloads con requisitos de soberanía
  regulatoria formal (art. 44 RGPD transferencias). En Fase 9, un banco interno con
  datos en EEA y SCC firmadas es suficiente.

**Reevaluar en Fase 10** si Compliance Santander eleva el requisito a soberanía formal.

---

## Compromisos de residencia de datos

Todos los siguientes artefactos permanecen dentro de eu-central-1 o eu-west-1 en todo momento:

| Artefacto                      | Servicio                                    | Región                   |
| ------------------------------ | ------------------------------------------- | ------------------------ |
| Prompts y respuestas jurídicas | Bedrock (in-region)                         | eu-central-1             |
| Audit trail                    | Aurora (primary) + S3 Object Lock (replica) | eu-central-1 + eu-west-1 |
| Vectores de documentos legales | Aurora pgvector via Bedrock KB              | eu-central-1             |
| Documentos BOE/EUR-Lex crudos  | S3 con versioning                           | eu-central-1             |
| Logs de sistema                | CloudWatch + log-archive S3                 | eu-central-1 + eu-west-1 |
| Trazas de agentes              | CloudWatch + Langfuse ECS                   | eu-central-1             |
| Backups Aurora                 | S3 cross-region replication                 | eu-central-1 → eu-west-1 |

**Cross-region inference para Bedrock:** si eu-central-1 está congestionado para Claude
Opus (latencia alta), se puede activar cross-region inference que puede enrutar a
us-east-1. Esto **solo se activa para llamadas sin datos de cliente** (e.g., razonamiento
técnico interno, clasificación de routing sin PII). Cualquier llamada con contexto de
consulta real permanece en eu-central-1. Esta restricción se impone vía SCP y se documenta
en ADR 0044.

---

## Contractual y compliance

- **AWS Data Processing Addendum (DPA):** firmado por Santander con AWS EU.
- **Standard Contractual Clauses (SCC):** cláusulas 2021/EU para transferencias
  intra-EEA documentadas.
- **AWS Sub-processors:** revisión anual de la lista de sub-procesadores de AWS que
  procesan datos en nombre de Santander.
- **CloudTrail org-wide:** todos los eventos de API en eu-central-1 y eu-west-1
  replicados automáticamente a la cuenta `log-archive` (ADR 0037).

---

## Consecuencias

- Cada ADR 0037–0043 verifica disponibilidad del servicio en eu-central-1 antes de adoptarlo.
- Si un servicio requerido no está disponible en eu-central-1, se documenta el riesgo y se
  busca alternativa en-region. No se acepta arquitectura que fuerce egreso EEA.
- El CDK (ADR 0043) hardcodea `env={"region": "eu-central-1"}` como default.
- Los GitHub Actions runners para deploy CI/CD no acceden a datos de producción; los
  artefactos de build no contienen datos de clientes.
