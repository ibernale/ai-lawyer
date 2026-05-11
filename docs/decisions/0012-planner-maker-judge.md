# ADR 0012 — Arquitectura Planner / Maker / Judge

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale

---

## Context

lex-agents v0.1.0 usa una arquitectura lineal: `Router → Specialist → Verifier`.
Funciona correctamente para consultas en una sola rama y jurisdicción.

Con la expansión a 6 ramas especialistas (ADR 0010), aparecen consultas que cruzan
ramas (e.g., "¿puede un banco sancionar a un empleado que filtró datos de un cliente?"
implica laboral + datos personales + penal económico) o que requieren razonamiento
sobre qué normativa priorizar cuando varias son aplicables. La arquitectura lineal
no tiene mecanismo para:

1. Descomponer consultas multi-rama en sub-tareas coordinadas
2. Definir criterios de éxito antes de que el especialista responda
3. Evaluar si la respuesta cubre todas las dimensiones requeridas

La evidencia de 2025–2026 muestra consistentemente que los LLMs no se autoevalúan
bien: un modelo que genera una respuesta y luego la evalúa tiene correlación alta
entre los sesgos del generador y los del evaluador. Para sistemas jurídicos esto
es especialmente relevante porque las hallucinations sutiles (cita de un artículo
que existe pero con interpretación incorrecta) son difíciles de detectar por el
mismo sistema que las genera.

---

## Decision

### Arquitectura Planner / Maker / Judge (PMJ)

```
ConsultRequest
    │
    ▼
┌─────────┐   PlannerOutput   ┌──────────────────────────┐
│ Planner │──────────────────▶│ Maker(s)                 │
│ (Opus)  │                   │  SpecialistA (Opus/Sonnet)│
└─────────┘                   │  SpecialistB (Sonnet)    │
                              │  [paralelo si multi-rama] │
                              └──────────┬───────────────┘
                                         │ MakerOutput
                                         ▼
                              ┌──────────────────────────┐
                              │ Judge                    │
                              │ (Opus, config distinta)  │
                              └──────────┬───────────────┘
                                         │ JudgeVerdict
                                    pass │ iterate (max 2)
                                         ▼
                                  ConsultResponse
```

---

### Planner

**Modelo:** Claude Opus 4.7 (`claude-opus-4-7`)
**Temperatura:** 0.1 (razonamiento determinista)

**Responsabilidades:**

1. Identificar ramas involucradas (0 a N ramas de ADR 0010)
2. Identificar jurisdicciones relevantes
3. Descomponer en sub-tareas si N > 1
4. Formular el "definition of done" (DoD) textual que el Judge usará como criterio
5. Seleccionar profundidad: `shallow` | `deep`
6. Pre-cargar memoria semántica relevante (docs/knowledge/ YAMLs, ADR 0013)

**`PlannerOutput`:**

```python
@dataclass
class SubTask:
    branch: str                  # rama de ADR 0010
    jurisdictions: list[str]
    query_focused: str           # query reformulada para esta sub-tarea
    rag_filters: dict            # filtros Qdrant adicionales

@dataclass
class PlannerOutput:
    original_query: str
    query_rewritten: str
    depth: Literal["shallow", "deep"]
    branches: list[str]
    jurisdictions: list[str]
    sub_tasks: list[SubTask]
    definition_of_done: str      # texto libre: qué debe cubrir la respuesta ideal
    output_type: str             # dictamen | nota | memo | análisis_riesgo
    planner_reasoning: str       # cadena de pensamiento del Planner (no se expone al usuario)
```

---

### Maker

**Modelo por defecto:** Claude Sonnet 4.6 (`claude-sonnet-4-6`) para sub-tareas
individuales. Claude Opus 4.7 para consultas de rama única marcadas como `deep`.

**Responsabilidades:**

1. Recibir el `brief` estructurado del Planner + contexto RAG
2. Generar la respuesta especialista con citas `[REF:n]`
3. Para consultas multi-rama: ejecutarse en paralelo por sub-tarea, luego sintetizar
4. Invocar el Verifier sobre su propia respuesta antes de entregarla al Judge

Los especialistas existentes (`regulatorio_bancario.py` y los nuevos de ADR 0010)
se refactorizan para recibir `SpecialistBrief` (derivado de `SubTask`) en lugar de
la `ConsultRequest` raw.

**`MakerOutput`:**

```python
@dataclass
class MakerOutput:
    answer: str
    citations: list[CitationMapping]
    verification: VerificationReport
    sub_task_id: str | None      # None si consulta de rama única
    metadata: dict               # modelo usado, latencia, tokens
```

Para consultas multi-rama, el sintetizador (`synthesizer.py` existente) integra los
`MakerOutput` de cada sub-tarea en una respuesta coherente antes de pasarla al Judge.

---

### Judge

**Modelo:** Claude Opus 4.7 con configuración diferenciada del Maker:

- Temperatura: 0.0 (máximo determinismo)
- System prompt distinto: el Judge recibe explícitamente el DoD del Planner y tiene
  instrucciones para identificar gaps, no para mejorar el estilo

La diferenciación de configuración (no de proveedor) es suficiente para reducir la
correlación de errores entre Maker y Judge. En la arquitectura PMJ, el Judge no
regenera respuestas; solo emite veredictos.

**`JudgeVerdict`:**

```python
@dataclass
class JudgeVerdict:
    decision: Literal["pass", "iterate", "escalate"]
    gaps: list[str]              # qué cubre el DoD que la respuesta no cubre
    confidence: float            # 0.0 – 1.0
    iteration: int               # 1 o 2
    reasoning: str               # no expuesto al usuario final
```

**Criterios de veredicto:**

- `pass`: respuesta cubre el DoD, no hay broken_refs, forbidden_claim_rate == 0
- `iterate`: hay gaps cubribles con más contexto RAG o reformulación; se devuelve al Maker con los gaps como brief adicional
- `escalate`: consulta requiere validación humana (e.g., conflicto normativo sin resolución clara, materia excluida del scope)

---

### Circuit breaker: máximo 2 iteraciones

El loop Maker ↔ Judge tiene un límite estricto de **2 iteraciones**. Si tras la
segunda iteración el Judge sigue emitiendo `iterate`, se devuelve la respuesta con:

```json
{
  "caveats": [
    "Esta respuesta no ha superado la validación interna completa. Requiere revisión prioritaria por jurista cualificado."
  ],
  "judge_status": "max_iterations_reached"
}
```

Este límite impide costes desbocados y hace el sistema predecible en latencia máxima.

---

### Condición de activación: `depth=deep`

La arquitectura PMJ completa se activa **únicamente** cuando:

| Condición                               | Umbral                        |
| --------------------------------------- | ----------------------------- |
| ≥ 2 ramas identificadas por el Planner  | siempre deep                  |
| ≥ 2 jurisdicciones distintas            | siempre deep                  |
| Flag `output_type = "dictamen"`         | siempre deep                  |
| Flag explícito del usuario `depth=deep` | siempre deep                  |
| Longitud de la query > 500 chars        | heurística, puede ser shallow |

Para `depth=shallow`, el flujo actual (Router → Specialist → Verifier) se mantiene
sin cambios. El Planner opera en modo reducido: solo routing y reformulación, sin DoD
ni loop Judge.

Justificación: el 70 % estimado de consultas serán shallow (una rama, una
jurisdicción, output tipo "nota"). Añadir overhead de Planner + Judge a consultas
simples aumentaría coste y latencia sin beneficio proporcional.

---

### Compatibilidad con la API pública

`POST /api/v1/consult` no cambia. El campo `routing` de `ConsultResponse` se extiende:

```json
{
  "routing": {
    "branch": "regulatorio_bancario_ue_es",
    "depth": "deep",
    "planner_sub_tasks": 2,
    "judge_iterations": 1,
    "judge_verdict": "pass"
  }
}
```

Los campos nuevos son opcionales y retrocompatibles. Clientes que solo leen `branch`
y `jurisdictions` no se ven afectados.

---

## Estimación de coste

| Profundidad          | Flujo                          | Tokens estimados (por consulta) | Coste estimado |
| -------------------- | ------------------------------ | ------------------------------- | -------------- |
| Shallow              | Router + Specialist + Verifier | ~15K                            | ~$0.05         |
| Deep (1 iteración)   | Planner + Maker + Judge×1      | ~40K                            | ~$0.15         |
| Deep (2 iteraciones) | Planner + Maker×2 + Judge×2    | ~70K                            | ~$0.25         |

El coste 2–3× de deep vs shallow se activa solo para el subconjunto de consultas que
lo requieren. Para el volumen estimado inicial (< 1000 consultas/día, 30 % deep), el
presupuesto mensual adicional es manejable.

---

## Alternatives considered

**Opción A: Self-critique (un solo modelo)** — El especialista genera la respuesta y
luego se autocritica. Descartado: la evidencia empírica muestra que los LLMs tienen
alta correlación entre sus propios errores de generación y sus errores de evaluación.
No resuelve el problema.

**Opción B: Debate entre dos modelos iguales** — Dos instancias del mismo modelo
debaten la respuesta. Descartado: sin diferenciación de configuración, el debate tiende
a converger rápidamente sin añadir valor real.

**Opción C: Evaluador externo no-LLM** — Pipeline determinista de validación (el
Verifier actual). Mantenido para CI (ADR 0009), insuficiente para consultas deep donde
la completitud semántica es el criterio principal.

---

## Consequences

**Positivo:**

- Consultas multi-rama producen respuestas integradas con DoD explícito, no concatenaciones de especialistas
- El Judge detecta gaps que el Verifier no puede (completitud semántica vs. integridad de citas)
- La separación de configuración Maker/Judge reduce correlación de errores

**Negativo/Riesgos:**

- La complejidad de implementación es sustancialmente mayor que la arquitectura lineal
- El Planner puede clasificar incorrectamente la profundidad; el circuit breaker protege contra costes desbocados pero no contra clasificaciones erróneas
- Con 2 iteraciones máximas, algunos casos genuinamente complejos recibirán respuestas marcadas como incompletas; esto es correcto y preferible a respuestas falsamente completas

**Neutral:**

- La arquitectura PMJ no reemplaza el Verifier existente (ADR 0008); el Verifier sigue corriendo dentro del Maker como capa de integridad de citas
