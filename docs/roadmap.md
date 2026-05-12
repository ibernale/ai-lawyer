# Roadmap — lex-agents

Estado a 2026-05-12. Actualizar tras cada release.

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

---

## Fase 8 — Capa de control y observabilidad operacional

> **Objetivo:** construir la infraestructura de gobierno necesaria para defender el sistema ante
> un comité y operarlo con seguridad. Fase 8 **no añade capacidades jurídicas nuevas**.

### Gate de entrada

- v0.3.0 mergeado y CI verde.
- ADRs 0030–0035 aprobados (esta fase 8.0 los firma).
- Al menos un ciclo de LeMAJ nightly sin alertas críticas.

### Sub-fases

#### Fase 8.0 — Planificación (este documento)

- ADR 0030: Langfuse OSS self-hosted como plataforma LLM-observability.
- ADR 0031: Cost tracking end-to-end (Anthropic API + estimación local + reconciliación diaria).
- ADR 0032: Kill switch global + component kill switches + feature flags (SQLite + API REST).
- ADR 0033: Modelo de roles viewer/operator/admin, JWT + campo `role`, compatible con SSO OIDC futuro.
- ADR 0034: Política de retención escalonada (traces 90d, Prometheus 365d, audit trail indefinido).
- ADR 0035: Tabla `audit_trail` append-only con cadena de hashes SHA-256.

#### Fase 8.1 — Infraestructura de observabilidad

- Desplegar Langfuse OSS en `docker-compose.dev.yml`.
- Integrar SDK Langfuse en OrchestratorV2, especialistas y LeMAJ.
- Crear `config/anthropic_prices.yaml` (tabla de precios versionada).
- Job nightly de sync con Anthropic Usage API (`ANTHROPIC_ADMIN_KEY`).
- Dashboard Grafana: coste por agente/modelo/día.

#### Fase 8.2 — Kill switches y persistencia

- Implementar tabla `system_state` y API `GET/PUT /api/v1/admin/state`.
- Implementar tabla `audit_trail` con triggers append-only y cadena de hashes.
- Implementar tabla `users` en `data/users.db` + `make admin-bootstrap`.
- Job nightly: verificación de integridad de `audit_trail` + alerta si cadena rota.
- Job nightly: eliminación de `audit_samples` > 365 días.
- Backup periódico de `audit_trail` a almacenamiento separado.
- Crear `docs/legal/data-retention.md` para revisión DPO.

#### Fase 8.3 — Operations Center (frontend)

- Nueva sección `/admin` en Next.js (solo rol `admin`).
- Panel de kill switches: tabla con estado de cada componente, botón toggle + campo reason.
- Panel de feature flags: lista editable con descripción y valor actual.
- Panel de usuarios: crear, desactivar, cambiar rol.
- Panel de costes: gráfico diario, desglose por agente/modelo, alerta de presupuesto.

#### Fase 8.4 — Audit trail UI y export

- Vista `/admin/audit` filtrable por actor, action_type, target, fechas.
- Diff visual de `before_state` / `after_state` para cada registro.
- Exportación CSV/JSON con meta-audit del propio export.
- Botón "Verificar integridad" que ejecuta `verify_chain()` y muestra resultado.

#### Fase 8.5 — Hardening y release v0.4.0

- Verificación `active=1` en cada request (no solo en login) para usuarios desactivados.
- Tests de integración: kill switch → API devuelve 503, flag toggle → comportamiento cambia.
- Prueba de penetración interna (auth bypass, inyección en reason, IDOR en audit trail).
- CHANGELOG v0.4.0 + tag + release.

### Gate de salida Fase 8

- Kill switch global funciona en < 1s desde PUT hasta primera consulta rechazada.
- `audit_trail` append-only demostrado: `UPDATE` y `DELETE` lanzan `ABORT`.
- Verificación de integridad de cadena pasa sobre 1000+ registros de prueba.
- Todos los roles: viewer, operator, admin probados con tests de integración.
- Langfuse UI muestra session replay de al menos 3 consultas reales.
- CI verde en rama antes de merge a main.

---

## Descartado (con justificación)

| Feature                            | Motivo                                                         |
| ---------------------------------- | -------------------------------------------------------------- |
| LLM-as-judge en CI                 | Coste, no-determinismo, latencia (ADR 0009)                    |
| RAG sobre PDFs escaneados          | OCR introduce ruido; priorizar fuentes estructuradas XML/JSON  |
| Chatbot conversacional multi-turno | Fuera de alcance MVP; complejidad de estado sin ganancia clara |
