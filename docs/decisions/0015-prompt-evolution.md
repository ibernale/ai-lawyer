# ADR 0015 — Prompt evolution con reflexión (GEPA-inspired)

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale

---

## Context

Los prompts de los especialistas (`docs/prompts/`) son la principal palanca de
calidad del sistema. Su evolución hoy es puramente manual: alguien lee un caso
fallido, intuye qué falta en el prompt y propone un cambio.

Con 6 ramas especialistas (ADR 0010) y un golden dataset creciendo hacia 150+ casos,
la revisión manual de todos los fallos después de cada nightly eval no es escalable.
Por otro lado, automatizar completamente la evolución de prompts en un sistema jurídico
es inaceptable: un cambio de prompt no revisado puede alterar el tono de cautela,
el alcance declarado, o la política de citas sin que nadie lo detecte hasta que un
usuario recibe un dictamen incorrecto.

GEPA (Generalized Evolutionary Prompt Agentification, 2025) y trabajos similares
demuestran que la reflexión textual sobre casos fallidos —usando el LLM para
analizar por qué falló, no solo para generar variantes aleatorias— produce mejoras
de prompt más consistentes que baselines de optimización automática. El valor está
en automatizar la **generación de hipótesis de mejora**, no en el loop completo.

---

## Decision

### Loop semi-automatizado con revisión humana obligatoria

```
Nightly eval run
    │
    ├─ casos_fallidos.jsonl (citation_recall < 0.7 OR concept_coverage < 0.5)
    │
    ▼
Reflection Agent (Opus, temp=0.2)
    │  Lee: casos fallidos + respuesta actual + prompt actual + ADRs relevantes
    │  Produce: análisis causal + diff propuesto
    │
    ▼
PR automático a prompt-evolution/<timestamp>
    │
    ▼
Revisión humana (jurista + engineer)
    │
    ├─ Aprobado → merge manual a main
    └─ Rechazado → PR cerrado con etiqueta "rejected:reason"
```

---

### Reflection Agent

**Modelo:** Claude Opus 4.7, temperatura 0.2 (algo de variabilidad para explorar
hipótesis, no pura reproducibilidad)

**Inputs:**
1. `failed_cases`: los `CaseResult` con `passed=False` del último nightly run
2. `current_prompt`: contenido de `docs/prompts/<branch>_vN.md`
3. `adr_context`: `docs/decisions/` (acceso de lectura completo)
4. `regression_cases`: 5 casos seleccionados aleatoriamente del golden dataset que
   el prompt actual pasa correctamente (para prueba de regresión)

**Output del Reflection Agent (estructura fija):**

```markdown
## Análisis causal
[Por qué fallaron los casos: patrones identificados en el prompt actual]

## Hipótesis de mejora
[Qué cambio específico abordaría los fallos observados]

## Diff propuesto
[Diff unificado del prompt: líneas eliminadas (-) y añadidas (+)]

## Consistencia con ADRs
[Verificación explícita: ¿el cambio contradice algún ADR? Si sí, señalarlo]

## Simulación de regresión
[Resultado esperado del prompt modificado sobre los 5 casos de regresión]
```

Si el Reflection Agent detecta que el diff propuesto contradice un ADR vigente,
**no suprime la propuesta** sino que la incluye con una sección `⚠️ CONFLICTO CON ADR NNNN`
para que el revisor humano tome la decisión consciente.

---

### Scope del Reflection Agent

**Puede proponer cambios a:**
- `docs/prompts/<branch>_vN.md` — instrucciones del especialista
- `docs/prompts/router_vN.md` — instrucciones de routing
- `docs/prompts/planner_vN.md` — instrucciones del Planner (ADR 0012)

**No puede proponer cambios a:**
- Código Python (packages/, apps/)
- Esquemas de datos (pydantic models, SQLite DDL)
- Configuración de infraestructura (docker-compose, GitHub Actions)
- ADRs (docs/decisions/)
- Configuración de evals (evals/config/weights.yaml)

Esta restricción de scope se implementa con una instrucción explícita en el system
prompt del Reflection Agent y se verifica en el PR check automático (diff path filter).

---

### Versionado de prompts

Los prompts usan semver de dos niveles: `MAJOR.MINOR`

| Tipo de cambio | Versión | Ejemplo |
|---------------|---------|---------|
| Cambio de política (scope, cautelas, formato de output) | MAJOR++ | v1.0 → v2.0 |
| Mejora puntual (añadir ejemplo, aclarar instrucción existente) | MINOR++ | v1.0 → v1.1 |

El runner de evals registra la versión exacta del prompt en `manifest.json`:
```json
{
  "prompt_versions": {
    "router": "1.2",
    "regulatorio_bancario": "2.0",
    "datos_personales": "1.0"
  }
}
```

Esto permite comparar runs con distintas versiones de prompt y aislar el efecto de
cada cambio.

**Convención de nombres de archivo:**
```
docs/prompts/regulatorio_bancario_v1.md   ← versión activa
docs/prompts/regulatorio_bancario_v2.md   ← propuesta en PR
```
Solo una versión está activa en cada momento; la configuración del especialista
apunta a la ruta explícita.

---

### Contenido mínimo del PR automático

El PR de `prompt-evolution/<timestamp>` incluye obligatoriamente:

1. **Caso fallido reproducible**: query + expected + actual, en formato YAML del
   golden dataset
2. **Análisis causal**: salida del Reflection Agent, sección "Análisis causal"
3. **Diff propuesto**: diff unificado del prompt (legible por humanos, no solo máquinas)
4. **Resultado de simulación**: el Reflection Agent ejecuta el prompt modificado
   contra los 5 casos de regresión y reporta pass/fail por caso
5. **Checklist de revisión** (template en `.github/PULL_REQUEST_TEMPLATE/prompt_evolution.md`):
   - [ ] El cambio no amplía el scope declarado del especialista sin ADR que lo justifique
   - [ ] Los caveats obligatorios siguen presentes
   - [ ] La simulación de regresión no introduce nuevos fallos
   - [ ] Un jurista cualificado ha revisado el impacto en el tono y alcance

---

### Salvaguarda anti-drift

El Reflection Agent tiene acceso de lectura a todos los ADRs para que sus propuestas
sean consistentes con las decisiones de arquitectura. Si un prompt evoluciona de forma
que contradice un principio de un ADR, el conflict check del PR lo marcará.

Adicionalmente, cada 10 versiones MINOR de un prompt, se requiere un **prompt audit**:
revisión humana completa del prompt actual vs. el original, verificando que no ha
derivado silenciosamente hacia un comportamiento no deseado (drift incremental).

---

## Referencia a GEPA

GEPA (2025) propone un loop evolutivo de prompts con reflexión textual sobre errores,
sin búsqueda aleatoria de variantes. Los resultados muestran mejoras consistentes vs.
baselines de optimización manual y automática, especialmente para tareas con semántica
compleja.

**Qué adoptamos de GEPA:**
- Reflexión textual sobre casos fallidos como mecanismo de generación de hipótesis
- Separación entre análisis causal y propuesta de cambio
- Validación de la propuesta contra casos de regresión antes de presentarla

**Qué no adoptamos:**
- El loop completo automatizado (reflexión → modificación → evaluación → siguiente iteración sin intervención humana). En contexto jurídico bancario, la automatización completa del loop de prompt evolution es inaceptable hasta que exista gobernanza formal de cambios en sistemas de asesoramiento.
- Búsqueda de población de prompts (evolución genética). El coste de evaluar N candidatos es desproporcionado; la reflexión dirigida es suficiente.

---

## Consequences

**Positivo:**
- Escala el proceso de mejora de prompts de manual-por-caso a semi-automático con revisión humana como gate
- El análisis causal del Reflection Agent genera documentación de por qué se hizo cada cambio, mejorando el conocimiento del equipo
- El conflict check con ADRs previene que la evolución de prompts deshaga decisiones de arquitectura

**Negativo/Riesgos:**
- Si el equipo aprueba PRs sin leer el análisis causal, el gate humano se convierte en teatro. El checklist de revisión mitiga pero no elimina este riesgo
- El Reflection Agent puede proponer cambios que mejoran los casos fallidos pero son jurídicamente incorrectos; por eso la revisión por jurista cualificado está en el checklist, no es opcional
- El prompt audit cada 10 versiones MINOR requiere tiempo de jurista; si no se cumple, el drift puede acumularse

**Neutral:**
- El framework es independiente del modelo base; si se cambia de Claude a otro modelo, el loop de reflexión sigue siendo válido
