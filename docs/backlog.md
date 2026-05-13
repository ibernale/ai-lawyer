# Backlog — lex-agents

Inventario exhaustivo de funcionalidades identificadas a 2026-05-13.
Basado en análisis del estado actual de la plataforma + benchmarking contra
Harvey AI, Thomson Reuters CoCounsel, LexisNexis Lexis+ Protégé, y requisitos
del EU AI Act / ECB supervisory priorities 2026.

Estado actual: v0.4.0 — governance completa, 6 agentes especialistas, RAG
híbrido, pipeline Dagster, Prometheus+Grafana, RBAC 3 roles.

---

## Cómo leer este documento

Cada funcionalidad tiene:

- **ID** único para referenciar en PRs y ADRs
- **Alcance** — `local` (puede implementarse sin infraestructura corporativa) o
  `fase-9+` (requiere cloud, contratos, o integraciones corporativas)
- **Bloque** — prioridad dentro del alcance local (1 = más urgente)

---

## Alcance local — Bloque 1 (bloqueante para uso real)

Funcionalidades sin las que el sistema no debería usarse para informar decisiones reales.

| ID    | Funcionalidad                              | Descripción                                                                                                                                                                                |
| ----- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| BL-01 | **Verificación de citas a nivel de claim** | Vincular cada afirmación individual a su chunk fuente con score de confianza. Actualmente la verificación es a nivel de respuesta completa. Es el principio no negociable #1 del proyecto. |
| BL-02 | **Confidence scoring por claim**           | Score de certeza individual por afirmación, expuesto en la UI, no solo por respuesta completa.                                                                                             |
| BL-03 | **Staleness detection**                    | Detectar automáticamente cuando una norma citada ha sido derogada o modificada comparando la fecha de vigencia del chunk con la fecha de la consulta.                                      |
| BL-04 | **Política de uso aceptable (AUP)**        | Documento formal — qué consultas están permitidas, qué decisiones no puede informar el sistema, cómo usar los outputs. Actualmente solo hay un disclaimer genérico.                        |

---

## Alcance local — Bloque 2 (calidad mínima exigible en banca)

| ID    | Funcionalidad                                 | Descripción                                                                                                                                                                                                                                                      |
| ----- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BL-05 | **Circular BdE**                              | Indexar circulares y guías de supervisión del Banco de España. Son la fuente más consultada en supervisión bancaria española y no están en EUR-Lex ni BOE con metadatos estructurados.                                                                           |
| BL-06 | **EBA Q&A y Guidelines**                      | Base de datos Single Rulebook Q&A de la EBA — crítica para interpretación de CRR/CRD. Respuestas vinculantes para entidades supervisadas.                                                                                                                        |
| BL-07 | **Monitor de cambios normativos con alertas** | Agente que vigila nuevas publicaciones en BOE/EUR-Lex/BdE/EBA y notifica proactivamente cuando hay cambios relevantes según el perfil de la consulta. Sin esto, el sistema puede dar respuestas correctas hoy que sean incorrectas mañana sin que nadie lo sepa. |
| BL-08 | **Dataset etiquetado por experto legal**      | Al menos un abogado valida un conjunto representativo de respuestas del sistema para establecer un baseline de fiabilidad. Prerequisito para confiar en los evals automatizados actuales.                                                                        |

---

## Alcance local — Bloque 3 (UX mínima usable)

| ID    | Funcionalidad                                   | Descripción                                                                                                                                                                                         |
| ----- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BL-09 | **Citas inline clicables**                      | Click en la cita → panel lateral con el chunk fuente original. Sin esto el usuario no puede verificar sin copiar la referencia a mano.                                                              |
| BL-10 | **Panel lateral de fuentes (source panel)**     | Diseño split: respuesta a la izquierda, chunks relevantes a la derecha. Estándar en Harvey, CoCounsel y Lexis+.                                                                                     |
| BL-11 | **Indicadores de confianza visuales por claim** | Color-coding por afirmación: verde (verificado contra fuente), amarillo (inferido), rojo (no verificable). Orienta la validación humana.                                                            |
| BL-12 | **Onboarding y tour guiado**                    | Flujo de primera vez que explica capacidades y limitaciones, especialmente el disclaimer "requiere validación humana". Un usuario nuevo sin contexto puede tratar el output como advice definitiva. |
| BL-13 | **Exportación enriquecida**                     | El export DOCX/XLSX actual no incluye los chunks fuente completos con metadatos. El export legal estándar incluye fuentes, scores y fecha del corpus.                                               |
| BL-14 | **Anti-sycophancy guard**                       | El modelo debe negarse explícitamente a apoyar claims normativos que no puede verificar, en lugar de generar autoridades plausibles. Guardia activa en el prompt del orquestador.                   |

---

## Alcance local — Bloque 4 (operaciones de un piloto)

| ID    | Funcionalidad                    | Descripción                                                                                                                                                                                                         |
| ----- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BL-15 | **Rate limiting por usuario**    | El slowapi actual es global. Con múltiples usuarios se necesita quota individual para evitar que un departamento consuma toda la capacidad.                                                                         |
| BL-16 | **Retrieval-level audit log**    | Registrar qué chunks se recuperaron, sus scores BM25 y semántico, y su versión en el momento de cada consulta. Si un abogado pregunta "¿de dónde sacó esto el sistema?", se necesita poder responder con precisión. |
| BL-17 | **Document version pinning**     | Cuando una norma se actualiza en Qdrant, las respuestas anteriores deben poder reproducirse contra la versión del corpus que existía en ese momento.                                                                |
| BL-18 | **Langfuse integration**         | Trazas LLM con scores de calidad por traza, distribución de costes por agente/modelo, detección de regresiones. Actualmente solo existe el template de configuración; la integración real no está implementada.     |
| BL-19 | **ESMA Q&A y Guidelines**        | Equivalente a BL-06 para MiFID II/EMIR/AIFMD. Necesario si el scope incluye mercados de capitales.                                                                                                                  |
| BL-20 | **CENDOJ productivo (full API)** | Acceso completo al repositorio de jurisprudencia del CGPJ, no solo el tier gratuito. Gate: autorización formal CGPJ.                                                                                                |

---

## Alcance local — Bloque 5 (capacidades agentic avanzadas)

| ID    | Funcionalidad                                              | Descripción                                                                                                                                                             |
| ----- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BL-21 | **Deep research con plan visible**                         | Agente multi-paso que genera un plan de investigación, lo ejecuta iterativamente y muestra el razonamiento de cada paso. Estándar en CoCounsel Deep Research y Harvey.  |
| BL-22 | **Q&A sobre documentos propios**                           | Upload de un PDF/DOCX por el usuario y consulta directa sobre su contenido contra el corpus regulatorio.                                                                |
| BL-23 | **Multi-document batch analysis**                          | Analizar un paquete de documentos (contrato completo, expediente regulatorio) de una vez contra el marco normativo.                                                     |
| BL-24 | **Razonamiento estructurado con chain-of-thought visible** | Exponer el chain-of-thought del agente al usuario, no solo la respuesta final. Aumenta confianza y permite detección temprana de errores de razonamiento.               |
| BL-25 | **Tool use / function calling externo**                    | El agente llama herramientas en tiempo real: verificar vigencia de una norma vía API BOE, consultar número de expediente CENDOJ.                                        |
| BL-26 | **Drafting agents**                                        | Redacción asistida de cláusulas contractuales con conformidad regulatoria integrada — cláusulas GDPR, contratos de crédito, avisos legales para productos de inversión. |

---

## Alcance local — Bloque 6 (UX avanzada)

| ID    | Funcionalidad                           | Descripción                                                                                                                                                              |
| ----- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| BL-27 | **Threads de investigación guardados**  | Guardar una línea de investigación como "expediente" y retomarla. Historial plano → estructura de sesiones.                                                              |
| BL-28 | **Search sobre historial de consultas** | Búsqueda full-text sobre consultas previas propias, no solo listado cronológico.                                                                                         |
| BL-29 | **Templates de consulta**               | Preguntas frecuentes parametrizables ("¿Cuáles son los requisitos de capital para [tipo] bajo [regulación]?") que el usuario rellena sin escribir desde cero.            |
| BL-30 | **Comparative analysis estructurada**   | Tabla de diferencias exportable para un requisito en múltiples jurisdicciones. La base existe (CrossJurisdictionCoordinator) pero no hay UI ni exportación estructurada. |
| BL-31 | **Compartir consulta**                  | Enlace compartible de una consulta con control de acceso por rol.                                                                                                        |
| BL-32 | **Modo comparativa**                    | Ejecutar la misma consulta con distintos parámetros y ver el diff de respuesta.                                                                                          |
| BL-33 | **Accesibilidad móvil**                 | Interfaz optimizada para móvil. Harvey reporta adopción móvil significativa en 2025.                                                                                     |

---

## Alcance local — Bloque 7 (calidad y evaluación continua)

| ID    | Funcionalidad                                   | Descripción                                                                                                                                                         |
| ----- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BL-34 | **Suite de evaluación de alucinaciones**        | Harness de benchmarks específico para regulación bancaria ES/UE. Los modelos actuales alucinan en 1 de cada 6 consultas en benchmarks legales (Stanford HAI, 2025). |
| BL-35 | **Drift detection de calidad**                  | Alertas cuando el LeMaJ score de producción cae por debajo del baseline o cuando la tasa de feedback "incorrecto" supera un umbral.                                 |
| BL-36 | **A/B testing de prompts en producción**        | Framework para comparar versiones de prompt en tráfico real con métricas de calidad, no solo en CI con evals sintéticos.                                            |
| BL-37 | **Feedback loop directo a mejora**              | El feedback de usuarios (aceptable/dudoso/incorrecto) alimenta automáticamente el proceso de mejora del RAG o fine-tuning.                                          |
| BL-38 | **Tracing end-to-end usuario→respuesta→fuente** | Los spans OTel cubren el backend. Falta el tracing del lado del frontend: cuánto tarda el usuario en leer la respuesta, si hace click en las citas, si exporta.     |
| BL-39 | **Red-teaming adversarial por expertos**        | Sesiones de red-teaming por expertos legales y de seguridad que complementen el adversarial automatizado.                                                           |

---

## Alcance local — Bloque 8 (memoria y personalización)

| ID    | Funcionalidad                                     | Descripción                                                                                                                                                                               |
| ----- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BL-40 | **Perfil de usuario jurídico**                    | El sistema aprende las áreas de especialización, jurisdicciones habituales y nivel de detalle preferido de cada usuario, ajustando respuestas sin que tenga que especificarlo.            |
| BL-41 | **Knowledge base corporativa**                    | Indexar el corpus de posiciones jurídicas internas del banco (dictámenes, interpretaciones propias), creando una capa de conocimiento propietario diferencial sobre la normativa pública. |
| BL-42 | **Actualización incremental del corpus**          | El pipeline Dagster hace resync completo. Se necesita actualización incremental (solo chunks modificados) para reducir coste y mantener frescura más cerca del tiempo real.               |
| BL-43 | **Agente de seguimiento de posición regulatoria** | Mantiene el "estado" de la posición del banco sobre cada regulación (gaps, plan de remediación) y responde teniendo en cuenta ese contexto.                                               |

---

## Alcance local — Bloque 9 (fuentes adicionales)

| ID    | Funcionalidad                                        | Descripción                                                                                                                     |
| ----- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| BL-44 | **DOUE / EUR-Lex nivel 2**                           | Reglamentos delegados, RTS/ITS de EBA/ESMA/EIOPA — actualmente no indexados.                                                    |
| BL-45 | **CNMV**                                             | Circulares, guías técnicas, Q&A sobre MiFID II, MAR, EMIR.                                                                      |
| BL-46 | **FSB, BIS y Comité de Basilea**                     | Documentos consultivos y standards internacionales de referencia.                                                               |
| BL-47 | **Fuentes comerciales (Aranzadi / La Ley / Tirant)** | Jurisprudencia comentada, doctrina. Gate: licencia comercial.                                                                   |
| BL-48 | **Benchmark público de regulación bancaria ES/UE**   | Contribuir o crear un benchmark específico comparable con BarExam/LegalBench para validación externa y comparativa de sistemas. |

---

## Fase 9+ (requiere infraestructura corporativa o contratos)

Estas funcionalidades son correctas pero no pueden implementarse en un despliegue local sin dependencias externas significativas.

| ID    | Funcionalidad                                              | Gate                                                           |
| ----- | ---------------------------------------------------------- | -------------------------------------------------------------- |
| F9-01 | **SSO con Azure AD / Okta (OIDC/SAML)**                    | Integración con IdP corporativo Santander                      |
| F9-02 | **IP allowlisting**                                        | Configuración de red corporativa                               |
| F9-03 | **MFA**                                                    | Infraestructura de identidad corporativa                       |
| F9-04 | **RBAC granular con grupos de AD**                         | Depende de F9-01                                               |
| F9-05 | **Zero Data Retention (Anthropic API)**                    | Contrato Enterprise con Anthropic                              |
| F9-06 | **Data residency EU formal**                               | Contrato y arquitectura cloud EU                               |
| F9-07 | **Cifrado en reposo**                                      | Requiere migración de SQLite + configuración Qdrant Enterprise |
| F9-08 | **Gestión de secretos (Vault / AWS Secrets Manager)**      | Infraestructura cloud                                          |
| F9-09 | **SOC 2 / ISO 27001**                                      | Proceso de auditoría externa                                   |
| F9-10 | **Despliegue cloud corporativo (AWS Frankfurt / on-prem)** | Presupuesto + arquitectura K8s                                 |
| F9-11 | **Autoscaling y load balancing**                           | Depende de F9-10                                               |
| F9-12 | **Multi-tenancy**                                          | Depende de F9-10                                               |
| F9-13 | **HA y Disaster Recovery**                                 | Depende de F9-10                                               |
| F9-14 | **Fuentes DMS Santander (SharePoint/iManage)**             | Acceso DMS corporativo + aprobación IT                         |
| F9-15 | **Plugin Word / Outlook**                                  | Distribución via Microsoft 365 store                           |
| F9-16 | **Notificaciones externas (Teams / Slack / email)**        | Integración con tenant Teams de Santander                      |
| F9-17 | **API pública documentada**                                | Política de APIs internas del banco                            |
| F9-18 | **Integración con GRC tools**                              | Depende de herramienta GRC interna                             |
| F9-19 | **Webhook outbound configurable**                          | Depende de F9-17                                               |
| F9-20 | **Conformity assessment package (EU AI Act art. 11)**      | Deadline agosto 2026 — requiere proceso formal                 |
| F9-21 | **Model card y data lineage**                              | Depende de F9-20                                               |
| F9-22 | **Post-market monitoring plan (EU AI Act art. 72)**        | Depende de F9-20                                               |
| F9-23 | **Registro EU AI Database**                                | Solo si se clasifica High-Risk                                 |
| F9-24 | **DPIA (GDPR art. 35)**                                    | Requiere DPO + Legal                                           |
| F9-25 | **Right-to-erasure endpoint**                              | Depende de F9-24                                               |
| F9-26 | **Episodic memory con gobernanza GDPR**                    | Depende de F9-24 — política de retención aprobada por DPO      |
| F9-27 | **Cache de respuestas semántico**                          | Evaluar si el ahorro de coste justifica la complejidad         |
| F9-28 | **Penetration testing externo**                            | Presupuesto de seguridad                                       |

---

## Referencias

- [Harvey AI Platform 2025](https://www.harvey.ai/platform)
- [Thomson Reuters CoCounsel Deep Research](https://medium.com/tr-labs-ml-engineering-blog/deep-research-in-westlaw-and-cocounsel-building-agents-that-research-like-lawyers-508ad5c70e45)
- [LexisNexis Lexis+ Protégé (mayo 2026)](https://www.globenewswire.com/news-release/2026/05/07/3289932/0/en/LexisNexis-Launches-Next-Evolution-of-Lexis-with-Prot%C3%A9g%C3%A9-the-Legal-AI-Platform-Built-on-the-Authority-Legal-Work-Demands.html)
- [Stanford HAI: AI models hallucinate 1 in 6 legal queries](https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries)
- [EBA Factsheet: AI Act implications for banking (nov 2025)](https://www.eba.europa.eu/sites/default/files/2025-11/d8b999ce-a1d9-4964-9606-971bbc2aaf89/AI%20Act%20implications%20for%20the%20EU%20banking%20sector.pdf)
- [ECB Supervisory Speech on AI (feb 2026)](https://www.bankingsupervision.europa.eu/press/speeches/date/2026/html/ssm.sp260224~6c5b64a77a.en.html)
