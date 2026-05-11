# Roadmap — lex-agents

Estado a 2026-05-11. Actualizar tras cada release.

---

## v0.1.0 — MVP (released)

Núcleo funcional: RAG híbrido + Orchestrator + Specialist + Verifier claim-level.
JWT auth, rate limiting, input validation, Prometheus + Grafana, Export Word,
feedback loop, golden dataset de evaluación.

Alcance: regulación bancaria UE+ES (CRR, CRD IV, BRRD, Ley 11/2015).

---

## Prioridad 1 — Calidad y cobertura (siguiente sprint)

### P1-A: Validación experta del dataset

- Revisar y marcar `expert_reviewed: true` en los 30 casos del golden dataset.
- Prerequisito para cualquier despliegue corporativo real.
- Responsable: jurista de cumplimiento.

### P1-B: CENDOJ — jurisprudencia bancaria

- Integrar sentencias del CENDOJ relacionadas con supervisión bancaria y resolución.
- Nuevo scraper `packages/ingest/scrapers/cendoj.py`.
- Ampliar el schema de CitationMapping con `court`, `date`, `ecli`.

### P1-C: Cobertura normativa ampliada

- CRR3 / CRD VI (en tramitación en 2026): seguimiento y pre-indexación.
- Circular 2/2023 Banco de España (MREL).
- Reglamento DORA (resiliencia operativa digital).

---

## Prioridad 2 — Multi-jurisdicción

### P2-A: Portugal (PT)

- Fontes: Banco de Portugal circular repository, DRE (Diário da República).
- Nuevo `jurisdiction_hint: PT`.
- Requiere prompt specialist en portugués.

### P2-B: Brasil (BR)

- Fontes: Banco Central do Brasil (BACEN), CMN resoluções.
- Alta demanda interna según feedback inicial.

### P2-C: México (MX)

- Fontes: CNBV circulares, DOF.
- Requiere validación de fuentes y scraper específico.

---

## Prioridad 3 — Derecho mercantil ES

- Ampliar alcance a M&A bancario, contratos de sindicación, derivados (EMIR).
- Requiere nuevo specialist `mercantil_es` y prompts dedicados.
- Volumen estimado: +500 documentos adicionales.

---

## Prioridad 4 — Modelo y retrieval

### P4-A: Fine-tuned reranker

- El reranker actual (cross-encoder) es genérico.
- Fine-tuning sobre pares query/fragment anotados por juristas.
- Estimación: requiere ~1000 pares positivos.

### P4-B: Evaluación LLM-as-judge (opcional)

- Actualmente rechazado por coste y determinismo (ver ADR 0009).
- Reconsiderar si: coste Haiku < $0.001/consulta y se tienen ground truths expertos.

### P4-C: Streaming de respuestas

- SSE o WebSocket para mostrar la respuesta en tiempo real.
- Mejora UX en consultas largas (latencia actual p95: ~12 s).

---

## Prioridad 5 — Gobernanza y producción

### P5-A: Revisión humana en el loop

- Dashboard de revisión para juristas: marcar citas como correctas/incorrectas.
- Feedback se usa para re-ranking y fine-tuning.

### P5-B: Autenticación corporativa

- SSO via SAML/OIDC con el IdP interno (Azure AD).
- Reemplazar el sistema de usuarios en JSON por integración con directorio.

### P5-C: Auditoría completa

- Tabla de auditoría en PostgreSQL (reemplazar SQLite para producción).
- Registro inmutable de quién consultó qué y cuándo.
- Exportación para cumplimiento GDPR.

### P5-D: SLA y alertas

- Definir SLO: latency_p95 < 15 s, error_rate < 1%, availability > 99.5%.
- PagerDuty / alertas Grafana para superación de umbrales.

---

---

## Fase 7 — Post-v0.2.0 (backlog)

Estas iniciativas están planificadas pero no tienen fecha confirmada.
Cada una tiene un gate explícito que debe cumplirse antes de iniciar la implementación.

### F7-A: CENDOJ — jurisprudencia bancaria y mercantil

- Integrar sentencias del CENDOJ (Centro de Documentación Judicial) relacionadas con
  supervisión bancaria, resolución y mercantil societario.
- **Gate:** autorización formal del CGPJ + revisión de licencias de uso comercial.
- Ampliar `CitationMapping` con campos `court`, `date`, `ecli`.

### F7-B: Memoria episódica

- Almacenar per-user/per-session consultas pasadas para permitir referencias contextuales.
- **Gate:** política de retención de datos RGPD aprobada por DPO; consentimiento usuario explícito.
- Requiere tabla `episodic_memory` en PostgreSQL + TTL configurable.

### F7-C: Despliegue corporativo SSO

- Autenticación SSO via SAML 2.0/OIDC con Azure AD corporativo (Grupo Santander).
- **Gate:** aprobación IT Security + Compliance; revisión de permisos de datos.
- Reemplaza sistema de usuarios JSON actual.

### F7-D: Validación experta del dataset completo

- Revisar los 30+ casos del golden dataset con juristas de cumplimiento.
- **Gate:** contratar tiempo de jurista; acuerdo de confidencialidad si se usan casos reales.
- Prerequisito para cualquier despliegue en producción real.

### F7-E: Ramas adicionales

- **Civil**: contratos bancarios, hipotecas, garantías (fuentes: CC, LEC, Código de Comercio).
- **Fiscal**: tributación de instrumentos financieros (fuentes: LIS, IRPF, IVA).
- **Procesal**: ejecución hipotecaria, procesos concursales (fuentes: LC, LEC).
- **Competencia**: abuso de posición dominante en servicios financieros (fuentes: TFUE, LDC).
- Cada rama requiere prompt dedicado, evaluación LeMAJ, y aprobación en ADR.

### F7-F: Más jurisdicciones LatAm

- **MX**: CNBV circulares, BANXICO disposiciones, DOF.
- **AR**: BCRA comunicaciones, CNV resoluciones.
- **CO**: SFC circulares externas.
- **Gate por jurisdicción**: fuentes estables + revisión de cobertura + jurista local para validación de prompts.

### F7-G: Inferencia federada / on-prem

- Opción de despliegue con modelos on-premise para datos clasificados.
- **Gate:** requisitos de residencia de datos definidos por regulación aplicable; viabilidad técnica evaluada.
- Candidatos: modelos open-source fine-tuned + vLLM / LM Studio.

---

## Descartado (con justificación)

| Feature                            | Motivo                                                         |
| ---------------------------------- | -------------------------------------------------------------- |
| LLM-as-judge en CI                 | Coste, no-determinismo, latencia (ADR 0009)                    |
| RAG sobre PDFs escaneados          | OCR introduce ruido; priorizar fuentes estructuradas XML/JSON  |
| Chatbot conversacional multi-turno | Fuera de alcance MVP; complejidad de estado sin ganancia clara |
