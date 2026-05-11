# ADR 0014 — LLM-as-Judge con Legal Data Points (LeMAJ)

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** ibernale
**Relación con ADR 0009:** extensión (no contradicción)

---

## Context

ADR 0009 rechazó LLM-as-judge para CI por cuatro razones: determinismo, coste,
latencia y circularidad (usar el mismo proveedor para generar y evaluar). Esas
razones siguen siendo válidas para el bloqueo de CI (smoke + full runs).

Sin embargo, la expansión a 6 ramas especialistas (ADR 0010) y la arquitectura PMJ
(ADR 0012) crean una necesidad nueva: evaluar la **completitud semántica y la
corrección interpretativa** de las respuestas, no solo la integridad de citas.
Las métricas heurísticas existentes (citation_recall, concept_coverage) son
necesarias pero no suficientes para detectar:

- Citas correctas con interpretación incorrecta del artículo
- Aplicación de norma de jurisdicción incorrecta
- Omisión de información que cambia la conclusión (completitud parcial)
- Caveats ausentes donde la norma es ambigua

Estos son exactamente los errores de mayor impacto en un sistema jurídico bancario.
Un framework de evaluación que los detecte sistemáticamente tiene valor aunque no sea
determinista ni barato, siempre que opere fuera del path crítico de CI.

---

## Decision

### LeMAJ: Legal Data Points + Panel de Jueces LLM

**Nivel de activación:** nightly únicamente. Nunca bloquea CI push/merge.

---

### Legal Data Point (LDP)

Un LDP es una **afirmación atómica verificable** extraída de la respuesta del agente.
Cada LDP tiene:

```python
@dataclass
class LegalDataPoint:
    ldp_id: str                      # "{trace_id}:ldp:{n}"
    claim_text: str                  # la afirmación atómica
    cited_source: str | None         # CELEX, BOE ID, o None si no citada
    cited_article: str | None        # número de artículo/apartado si aplica
    jurisdiction: str | None         # jurisdicción implícita
    extracted_from_response_offset: int
```

**Algoritmo de extracción de LDPs:**
1. El texto de respuesta se segmenta en oraciones usando spaCy (idioma ES)
2. Cada oración con verbo modal o predicado normativo (debe, puede, prohíbe, obliga,
   establece, requiere…) se candidata como LDP
3. Se asocia al `[REF:n]` más cercano como `cited_source`
4. Un LLM de extracción (Haiku, temperatura 0.0) convierte la oración candidata en
   afirmación atómica normalizada

---

### Cinco criterios de evaluación por LDP

| Criterio | Definición | Escala |
|----------|-----------|--------|
| `factual_support` | ¿El chunk citado contiene base textual para el LDP? | pass / fail / uncertain |
| `normative_accuracy` | ¿La interpretación del precepto citado es jurídicamente defendible? | pass / fail / uncertain |
| `jurisdictional_correctness` | ¿Se aplica la norma de la jurisdicción correcta para la cuestión planteada? | pass / fail / uncertain |
| `completeness_partial` | ¿El LDP omite información del mismo chunk que cambiaría materialmente la conclusión? | pass / fail / uncertain |
| `caveat_appropriateness` | ¿El LDP lleva las cautelas necesarias si la norma es ambigua, está en revisión, o tiene excepciones relevantes? | pass / fail / uncertain |

`uncertain` significa: el juez no tiene suficiente información en el contexto para
decidir; no es sinónimo de "fallo". Los `uncertain` no penalizan pero disparan
un flag de revisión humana.

---

### Panel de jueces

**3 configuraciones distintas + 1 meta-juez:**

| Rol | Modelo | Temperatura | Prompt variant |
|-----|--------|-------------|----------------|
| Juez A | claude-opus-4-7 | 0.1 | Criterios literales del ADR |
| Juez B | claude-opus-4-7 | 0.3 | Criterios + ejemplos few-shot de fallos pasados |
| Juez C | claude-sonnet-4-6 | 0.1 | Criterios con chain-of-thought explícito |
| Meta-juez | claude-opus-4-7 | 0.0 | Árbitro: recibe los 3 veredictos + razonamientos, decide |

**Protocolo de decisión:**
- Los 3 jueces coinciden → decisión final sin meta-juez (ahorro de coste)
- 2 de 3 coinciden → mayoría, meta-juez solo revisa si `uncertain` está en minoría
- Desacuerdo total → meta-juez arbitra con razonamiento explícito
- Meta-juez también `uncertain` → el LDP se marca `human_review_required: true`

**Presupuesto máximo por run nightly:** $15. Si el dataset crece y el coste supera
el umbral, reducir el panel a Juez A + Meta-juez en vez de los 3.

---

### Métricas derivadas

```python
@dataclass
class LeMAJRunMetrics:
    run_id: str
    timestamp: str
    ldps_total: int
    ldps_pass: int               # todos los criterios pass
    ldps_fail: int               # al menos un criterio fail
    ldps_uncertain: int          # al menos un uncertain, ningún fail
    ldps_human_review: int
    ldp_accuracy: float          # ldps_pass / ldps_total
    response_coverage: float     # respuestas con ldp_accuracy >= 0.9 / total responses
    inter_judge_kappa: float     # Cohen's Kappa entre Juez A y Juez B
    kappa_alert: bool            # True si kappa < 0.6
```

**Cohen's Kappa bajo (< 0.6) es señal de tarea mal definida**, no solo de jueces
inconsistentes. Si `kappa_alert` es True, el equipo revisa los criterios del
ADR antes de atribuir el problema al sistema evaluado.

---

### Extensión del framework de evals (Fase 4)

LeMAJ **extiende**, no reemplaza, el framework existente:

```
python -m evals run   → métricas heurísticas (CI gate, sin cambios)
python -m evals judge → extracción LDPs + panel de jueces + LeMAJRunMetrics
```

Nuevos campos en `CaseResult`:
```python
ldp_accuracy: float | None = None
ldps_human_review: int | None = None
inter_judge_kappa: float | None = None
```

Los runs de `evals judge` se almacenan en `evals/reports/lemaj_<timestamp>/`:
- `ldps.jsonl` — un JSON por LDP con todos los veredictos
- `lemaj_metrics.json` — `LeMAJRunMetrics`
- `human_review.md` — lista de LDPs marcados para revisión

Los reports de `evals run` (CI) no incluyen datos LeMAJ; los pipelines son
independientes para no contaminar las métricas de CI con evaluaciones no deterministas.

---

## Relación con ADR 0009

ADR 0009 rechazó LLM-as-judge por cuatro razones. LeMAJ aborda cada una:

| Razón ADR 0009 | Respuesta LeMAJ |
|----------------|-----------------|
| Determinismo (flaky CI) | LeMAJ no corre en CI; nightly únicamente |
| Coste ($5-10/run) | Presupuesto máximo $15/run nightly; aceptable con frecuencia diaria |
| Latencia (dobla wall-clock) | No está en el path crítico; corre asíncronamente tras el run heurístico |
| Circularidad (mismo proveedor) | Panel con 3 configuraciones distintas reduce correlación; Cohen's Kappa mide el grado de acuerdo independiente |

ADR 0009 sigue vigente para CI. LeMAJ opera en la capa de evaluación profunda donde
el coste y el no-determinismo son aceptables.

---

## Consequences

**Positivo:**
- Detecta clases de errores (interpretación normativa incorrecta, omisión de caveats) que las métricas heurísticas no pueden detectar
- Cohen's Kappa como métrica de calidad del propio sistema de evaluación es un mecanismo de auto-diagnóstico valioso
- La separación CI/LeMAJ protege la velocidad de desarrollo sin sacrificar profundidad de evaluación

**Negativo/Riesgos:**
- El costo de $15/run es aceptable hoy; si el golden dataset crece a 200+ casos puede requerir sampling estratificado
- La extracción de LDPs con NLP (spaCy + LLM) puede ser imprecisa para texto jurídico denso; requiere validación humana de la calidad de la extracción antes de confiar en las métricas
- La definición de `normative_accuracy` es parcialmente subjetiva; el human_review_required actúa como válvula de seguridad

**Neutral:**
- La arquitectura del panel es escalable: añadir un cuarto juez o cambiar modelos es un cambio de configuración, no de código
