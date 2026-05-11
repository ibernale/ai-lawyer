# ADR 0010 — Expansión de ramas especialistas

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale

---

## Context

lex-agents v0.1.0 opera una única rama especialista: `regulatorio_bancario_ue_es`.
El equipo jurídico interno de Santander gestiona consultas en al menos ocho dominios
distintos. Confinar el sistema a regulación bancaria limita su valor y obliga a los
usuarios a cambiar de herramienta para el 80 % de las consultas del día a día.

Con el MVP validado técnicamente —RAG híbrido, Orchestrator, Verifier, evals—, el
momento es adecuado para expandir el catálogo de ramas sin comprometer la calidad
de la rama existente.

---

## Decision

### Cinco ramas nuevas, en este orden de implementación

| Orden | Rama | Código interno | Justificación de prioridad |
|-------|------|----------------|---------------------------|
| 1 | Datos personales / RGPD | `datos_personales_rgpd` | Alta demanda del DPO interno; fuentes muy delimitadas (AEPD + EDPB); regulación estable y bien estructurada |
| 2 | Laboral | `laboral_es` | Mayor volumen estimado de consultas internas; ET + convenios sectoriales bancarios + jurisprudencia TS Sala Social |
| 3 | Mercantil / societario | `mercantil_societario` | Complementa operaciones M&A y reestructuraciones bancarias ya en roadmap; Registro Mercantil + TRLSC + LME |
| 4 | Penal económico | `penal_economico` | Compliance penal bancario (Ley Orgánica 1/2015, delitos societarios, blanqueo); crece con normativa AMLD6 |
| 5 | Administrativo sancionador | `administrativo_sancionador` | Procedimiento sancionador CNMV/BdE/AEPD; recurso contencioso-administrativo sobre resoluciones supervisoras |

### Ramas explícitamente excluidas de esta fase

| Rama excluida | Razón |
|---------------|-------|
| Civil general | Amplitud máxima (CC, obligaciones, contratos, familia, sucesiones); validación experta muy costosa; valor marginal bajo para banca vs. otras ramas |
| Fiscal | Normativa mutable, interpretaciones administrativas volátiles (DGT), riesgo alto de hallucination con consecuencias económicas directas; requiere equipo especializado en tax |
| Procesal | Fuertemente procedimental, variación autonómica, utilidad limitada sin integración con LexNET |
| IT / IP | Requiere fuentes específicas (OEPM, EUIPO, WIPO) no conectadas aún; demanda interna estimada baja |
| Competencia | CNMC + DG Comp; casuística muy case-specific; riesgo de citar precedentes con matices que requieren experto |

La exclusión es temporal. Estas ramas se reevaluarán en Fase 7 según uso real de las ramas activas y disponibilidad de validación experta.

---

## Patrón de implementación: `packages/agents/base/`

Para evitar duplicación de código entre especialistas, se factoriza el patrón común:

```
packages/agents/src/lex_agents_agents/
├── base/
│   ├── __init__.py
│   ├── specialist.py        # BaseSpecialist ABC
│   ├── specialist_config.py # SpecialistConfig dataclass
│   └── prompt_mixin.py      # PromptVersionMixin
├── regulatorio_bancario.py  # ya existe, migra a heredar BaseSpecialist
├── datos_personales.py      # nueva
├── laboral.py               # nueva
├── mercantil.py             # nueva
├── penal_economico.py       # nueva
└── administrativo.py        # nueva
```

`BaseSpecialist` expone:
- `run(brief: SpecialistBrief) -> SpecialistResponse` — interfaz única para el Orchestrator/Planner
- `_build_prompt(context: str, query: str) -> str` — hook sobreescribible por especialista
- `_validate_response(resp: str) -> VerificationInput` — prepara la respuesta para el Verifier

`SpecialistConfig` contiene: `branch_name`, `jurisdictions`, `prompt_path`, `qdrant_filter`, `output_types_supported`.

### Colección Qdrant: multi-tenant con filtro `domain=`

Se usa **una sola colección** `lex_legal_docs` con campo de payload `domain: str` (e.g., `"datos_personales"`, `"laboral"`). El retriever aplica `FieldCondition(key="domain", ...)` como filtro adicional.

Razones:
- Evita gestionar N colecciones con vectores duplicados (normas que cruzan dominios, e.g., LOPD ↔ laboral)
- Simplifica el Planner multi-rama: un solo cliente Qdrant, múltiples filtros
- Facilita búsquedas cross-domain cuando el Planner lo requiere

Alternativa descartada: colecciones separadas por rama. Rechazada porque los documentos cross-domain (LOPDGDD, normativa CNMV que toca mercantil y penal) se duplicarían o quedarían sin indexar en alguna rama.

---

## Mapping por rama

| Rama | Jurisdicciones | Fuentes primarias | Prompt path | Filtro Qdrant |
|------|---------------|-------------------|-------------|---------------|
| datos_personales_rgpd | ES, EU | AEPD resoluciones, EDPB guidelines, RGPD, LOPDGDD | `docs/prompts/datos_personales_v1.md` | `domain=datos_personales` |
| laboral_es | ES | BOE (ET, LGSS, convenios), TS Sala Social (CENDOJ-AMBER) | `docs/prompts/laboral_v1.md` | `domain=laboral` |
| mercantil_societario | ES, EU | BOE (TRLSC, LME, LSC), BORME, EUR-Lex (directivas societarias) | `docs/prompts/mercantil_v1.md` | `domain=mercantil` |
| penal_economico | ES, EU | BOE (CP, LO 1/2015), EUR-Lex (AMLD6, DORA art. penales) | `docs/prompts/penal_economico_v1.md` | `domain=penal_economico` |
| administrativo_sancionador | ES | BOE (LPAC, LJCA), CNMV/BdE circulares y resoluciones | `docs/prompts/administrativo_v1.md` | `domain=administrativo` |

---

## Criterio de "rama lista" para activación en producción

Una rama puede activarse cuando cumple **todos**:

1. Prompt versionado en `docs/prompts/<rama>_v1.md` con sección de cautelas obligatorias
2. ≥ 5 casos en `evals/golden_dataset/` con `domain=<rama>` (al menos 1 easy, 1 medium, 1 hard, 1 negativo)
3. Tests unitarios del especialista en `packages/agents/tests/test_<rama>.py`
4. `SpecialistConfig` registrado en el router del Orchestrator
5. Documentación de fuentes en `docs/sources/<rama>.md`
6. `expert_reviewed: false` explícito en todos los casos del golden dataset hasta validación

---

## Consequences

**Positivo:**
- El patrón `BaseSpecialist` reduce el coste de añadir ramas futuras a ~2 días por rama vs. ~2 semanas desde cero
- La colección unificada permite búsquedas cross-domain necesarias para el Planner (ADR 0012)
- Las ramas tienen criterios de aceptación objetivos; no se activan hasta cumplirlos

**Negativo/Riesgos:**
- Cada rama nueva aumenta la superficie de hallucinations posibles; la validación experta por rama es costosa
- La colección unificada requiere disciplina en el campo `domain` durante la ingesta; un error de etiquetado contamina resultados
- Las 5 ramas nuevas suponen ~5× más casos necesarios en el golden dataset para mantener cobertura equivalente

**Neutral:**
- La rama `regulatorio_bancario_ue_es` existente se migra para heredar `BaseSpecialist` en la misma sub-fase que se implementa la primera rama nueva; coste estimado: medio día
