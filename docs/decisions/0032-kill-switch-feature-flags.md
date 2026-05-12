# ADR 0032 — Kill Switch y Feature Flags

- **Estado:** Accepted
- **Fecha:** 2026-05-12
- **Autores:** @ibernale
- **Fase:** 8.0 — Capa de control y observabilidad operacional

---

## Contexto

En Fase 7 el sistema pasó de ser un prototipo técnico a una plataforma con capacidades reales: 9 fuentes de ingesta, 6 ramas especialistas, análisis de documentos, evolución automática de prompts y suite adversarial. Este poder requiere mecanismos de control equivalentes.

Escenarios que justifican kill switches y feature flags:

- **Incidente de calidad**: el agente Planner genera respuestas incorrectas por un prompt defectuoso → necesitamos pausar solo el modo `deep` sin tumbar el sistema.
- **Fuente comprometida**: CENDOJ devuelve datos erróneos → pausar la fuente sin afectar al resto.
- **Ventana de mantenimiento**: actualización de Qdrant → modo read-only mientras dura.
- **Despliegue gradual**: activar nueva feature (PDF nativo) solo para usuarios admin antes de producción.
- **Reducción de coste urgente**: degradar panel de 3 jueces a 1 temporalmente.

Sin estos controles, la única opción es un `docker-compose down`, que es destructivo y tarda minutos.

---

## Decisión

**Implementar tres niveles de control operativo con propagación diferenciada**, almacenados en SQLite y expuestos vía API REST con rol `admin`.

---

## Nivel 1 — Global Kill Switch

### Comportamiento

Cuando `global_kill_switch = true`:
- **Cero llamadas LLM**: ningún agente invoca la Anthropic API.
- **Respuesta fija**: la API devuelve HTTP 503 con body:
  ```json
  {"error": "service_unavailable", "message": "Sistema pausado por administración.", "paused_at": "<ISO-8601>", "reason": "<motivo>"}
  ```
- **Ingesta Dagster**: jobs en curso terminan su step actual y no inician nuevos.
- **UI**: banner rojo en frontend: "Sistema temporalmente pausado. Consulte con administración."

### Trazabilidad obligatoria

- Activar o desactivar el kill switch **requiere `reason` no vacío**.
- Toda acción se registra inmediatamente en `audit_trail` (ADR 0035) con `action_type = kill_switch_engage | kill_switch_release`.
- Propagación: **inmediata** (invalida caché de agentes al instante, sin TTL).

---

## Nivel 2 — Component Kill Switches

### Por agente

| Key | Agente controlado |
|---|---|
| `agent.router` | RoutingAgent (clasifica la consulta entrante) |
| `agent.planner` | LegalPlanner (descompone queries complejas) |
| `agent.specialist.regulatorio_bancario` | Especialista regulatorio bancario |
| `agent.specialist.datos_personales` | Especialista datos personales RGPD |
| `agent.specialist.laboral` | Especialista laboral |
| `agent.specialist.mercantil` | Especialista mercantil societario |
| `agent.specialist.penal_economico` | Especialista penal económico |
| `agent.specialist.administrativo` | Especialista derecho administrativo |
| `agent.judge` | LegalJudge (iteración de calidad) |
| `agent.synthesizer` | CrossJurisdictionCoordinator (síntesis multi-rama) |
| `agent.document_analyst` | Document Analysis Agent |

Cuando un agente está pausado, las consultas que lo requieren devuelven aviso de cobertura reducida (no error fatal).

### Por fuente

| Key | Fuente controlada |
|---|---|
| `source.boe` | BOE (Boletín Oficial del Estado) |
| `source.eurlex` | EUR-Lex / CELLAR |
| `source.aepd` | AEPD resoluciones |
| `source.edpb` | EDPB guidelines |
| `source.bde` | Banco de España circulares |
| `source.eba` | EBA Single Rulebook |
| `source.esma` | ESMA Q&As |
| `source.legislation_uk` | legislation.gov.uk |
| `source.fca` | FCA Handbook |
| `source.cendoj` | CENDOJ jurisprudencia |

Al pausar una fuente:
1. El asset Dagster correspondiente entra en estado `paused` (no se materializa aunque haya schedule).
2. El `HybridRetriever` excluye esa fuente de los resultados de búsqueda (filtro por `source_id`).
3. Las consultas que dependían de esa fuente reciben aviso: *"Cobertura reducida: fuente X temporalmente no disponible."*

### Por capacidad

| Key | Capacidad controlada |
|---|---|
| `capability.document_analysis` | Análisis de documentos (Document Agents) |
| `capability.comparative_law` | Módulo de derecho comparado |
| `capability.prompt_evolution_loop` | Pipeline de evolución de prompts (FailureAnalyzer→PROpener) |
| `capability.adversarial_testing` | Ejecución de suites adversariales |

---

## Nivel 3 — Feature Flags

Controlan comportamiento fino sin requerir redespliegue.

| Flag | Tipo | Valor inicial Fase 8 | Descripción |
|---|---|---|---|
| `depth_deep_enabled` | bool | `true` | Activa modo PMJ completo (Planner+Coordinator+Judge) |
| `cendoj_dev_mode_enabled` | bool | `false` | CENDOJ en modo dev (cuota estricta, solo admin) |
| `high_fidelity_document_pdf` | bool | `false` | Usa Claude PDF nativo en Document Agents (coste ×3) |
| `adversarial_blocking` | bool | `true` | Suites adversariales bloquean CI si fallan |
| `llm_judge_panel_size` | int | `3` | Número de jueces LeMAJ activos (1 ó 3) |
| `new_prompt_versions_auto_promote` | bool | `false` | **Invariante de gobernanza: NUNCA true** (ADR 0021) |

---

## Storage: tabla `system_state`

```sql
CREATE TABLE system_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,       -- JSON serializado (bool, int, string)
    updated_at  TEXT NOT NULL,       -- ISO-8601 UTC
    updated_by  TEXT NOT NULL,       -- user_id
    reason      TEXT                 -- obligatorio para kill switches
);
```

La tabla se inicializa en bootstrap con los valores por defecto de Fase 8. Los cambios se escriben con transacción atómica que también inserta en `audit_trail`.

---

## API

```
GET  /api/v1/admin/state           # lee todo el estado (requiere rol admin)
GET  /api/v1/admin/state/{key}     # lee una entrada
PUT  /api/v1/admin/state/{key}     # escribe (requiere admin + reason para kill switches)
```

Body para PUT:
```json
{"value": true, "reason": "Ventana de mantenimiento Qdrant 02:00–04:00 UTC"}
```

---

## Propagación y caché

| Tipo de cambio | Propagación |
|---|---|
| Kill switch global | **Inmediata** — invalida toda caché de agentes (broadcast interno) |
| Component kill switch | TTL 5s — agentes releen estado en cada consulta |
| Feature flag | TTL 5s — suficiente para la mayoría de casos |

El TTL de 5s evita que múltiples instancias del API hagan storm de lecturas SQLite. Para el kill switch global, la invalidación inmediata es no negociable (seguridad operacional).

---

## Alternativas consideradas

| Alternativa | Razón de descarte |
|---|---|
| **LaunchDarkly** | Cloud-only, lock-in, datos de configuración salen del perímetro local, coste mensual. |
| **Unleash OSS** | Sobredimensionado para MVP: requiere server separado, SDK, UI compleja. Podría adoptarse en Fase 9. |
| **Variables de entorno** | No permiten cambio en caliente sin redeploy. No tienen audit trail. No soportan granularidad por agente/fuente. |
| **Redis + pub/sub** | Añade dependencia de infraestructura solo para flags. SQLite con TTL corto es suficiente para escala MVP. |

---

## Consecuencias

**Positivas:**
- Control granular sin tocar código ni redesplegar.
- Audit trail completo de quién cambió qué y por qué (integrado con ADR 0035).
- Degradación graceful: pausar una fuente o agente no tumba el sistema.
- `new_prompt_versions_auto_promote = false` como invariante protege la gobernanza de prompts (ADR 0021).

**Negativas / Riesgos:**
- Riesgo de "flag sprawl" si se añaden flags sin disciplina. Política: cada flag nuevo requiere ADR o nota en PR explicando cuándo se eliminará.
- El TTL de 5s introduce una ventana de inconsistencia entre instancias del API (aceptable en MVP monolítico).

**Deuda técnica aceptada:**
- UI de Operations Center (sub-fase 8.3) para gestionar flags sin necesidad de llamadas API directas.
- Migración a Unleash o equivalente si el número de flags supera 20 en Fase 9.

---

## Referencias

- [ADR 0021](0021-prompt-evolution-policy.md) — Invariante no-auto-promote de prompts
- [ADR 0033](0033-roles-auth.md) — Modelo de roles (admin requerido)
- [ADR 0035](0035-immutable-audit-trail.md) — Audit trail de cambios de estado
