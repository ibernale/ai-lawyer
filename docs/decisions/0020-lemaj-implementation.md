# ADR 0020 — LeMAJ: Legal Multi-Agent Judge Implementation

**Estado:** Aceptado  
**Fecha:** 2026-05-11  
**Autores:** equipo lex-agents  
**Supersede:** —  
**Relacionados:** ADR 0014 (política LeMAJ), ADR 0021 (prompt evolution)

---

## Contexto

El sistema lex-agents produce respuestas a consultas jurídicas complejas que combinan regulación EU y ES. Las métricas de evaluación existentes (Fase 4) miden cobertura de conceptos y tasa de alucinaciones a nivel de caso, pero no ofrecen granularidad sobre qué afirmaciones concretas son incorrectas ni sobre el acuerdo entre evaluadores. El sistema LeMAJ (Legal Multi-Agent Judge) implementa la evaluación granular requerida por ADR 0014.

---

## Decisión

### Unidad de evaluación: Legal Data Point (LDP)

Un LDP es una afirmación jurídica atómica extraída de la respuesta del agente:

```
LegalDataPoint(
    ldp_id,           # "<case_id>-LDP-<n>"
    claim_text,       # afirmación atómica (≤ 1 oración)
    claim_type,       # factual | interpretive | procedural | cautionary
    supporting_refs,  # [REF:n] encontradas en claim_text o contexto
    jurisdiction_scope,  # ES | EU | ES+EU | global | unknown
    context,          # párrafo padre de la respuesta original
)
```

La extracción se realiza con `LDPDecomposer` (claude-opus-4-7, temp=0.0, tool_use) con fallback heurístico basado en segmentación de oraciones si la API falla.

### Panel de 3 jueces

| Juez | Clase    | Modelo                    | Temperatura | Prompt                                                  |
| ---- | -------- | ------------------------- | ----------- | ------------------------------------------------------- |
| A    | `JudgeA` | claude-opus-4-7           | 0.0         | `lemaj/judge/vA.md` — instrucciones literales           |
| B    | `JudgeB` | claude-opus-4-7           | 0.0         | `lemaj/judge/vB.md` — mismas instrucciones + 2 few-shot |
| C    | `JudgeC` | claude-haiku-4-5-20251001 | 0.0         | `lemaj/judge/vA.md` — modelo distinto, mismo prompt     |

La variación deliberada (prompt B con few-shot, modelo C más rápido) aumenta la diversidad del panel sin sesgo de formación idéntica.

Cada juez evalúa 5 dimensiones por LDP:

| Dimensión                    | Qué mide                                       |
| ---------------------------- | ---------------------------------------------- |
| `factual_support`            | Base factual verificable en chunks recuperados |
| `normative_accuracy`         | Interpretación jurídica defendible             |
| `jurisdictional_correctness` | Jurisdicción correcta (ES/EU/UK/global)        |
| `completeness_partial`       | Omisiones materiales                           |
| `caveat_appropriateness`     | Cautelas necesarias presentes                  |

Cada dimensión: `supported` / `partial` / `unsupported`. Veredicto global `overall` ídem.

Los tres jueces se ejecutan en paralelo (`asyncio.gather(..., return_exceptions=True)`).

### Regla de consenso y meta-juez

- Si los tres coinciden en `overall` → `final_verdict = overall`, `meta_judge_used = False`.
- Si hay cualquier desacuerdo → `MetaJudge.arbitrate()`.

`MetaJudge`: claude-opus-4-7, temp=0.0, prompt `lemaj/meta_judge/v1.md`. Recibe los 3 veredictos y emite veredicto final vía tool_use con campo `low_confidence`.

- Si `low_confidence = True` → `final_verdict = "review_required"`.
- Los LDP con `review_required` se excluyen de métricas automáticas y se incluyen en `lemaj_report.md` para revisión humana.

### Métricas de acuerdo inter-juez (Kappa)

Se calculan por dimensión:

- Cohen's Kappa para pares A-B, A-C, B-C (usando sklearn `cohen_kappa_score`).
- Fleiss' Kappa para los 3 jueces simultáneamente (implementación manual con numpy).

Umbral: **Fleiss κ < 0.6** en una dimensión indica que la definición de esa dimensión en el prompt del juez es ambigua. El flag `low_kappa_dimensions` aparece en el reporte y requiere revisión del prompt del panel (no del especialista). Esta distinción es importante: kappa bajo es un problema de calibración del juez, no del especialista.

### Artefactos de salida

Por run de evaluación (directorio `evals/reports/<run_id>/lemaj/`):

| Archivo                | Formato  | Contenido                                  |
| ---------------------- | -------- | ------------------------------------------ |
| `lemaj_verdicts.jsonl` | JSONL    | Un `LDPVerdict` por línea                  |
| `lemaj_metrics.json`   | JSON     | `LeMAJRunMetrics` con tasas, kappas, coste |
| `lemaj_report.md`      | Markdown | Resumen tabular + LDPs `review_required`   |

### Presupuesto de coste

Máximo **$15 USD por run** de evaluación completo, registrado en `LeMAJRunMetrics.cost_usd`. Si se supera en dos runs consecutivos, se revisará si reducir el número de casos o el modelo de algún juez.

### Fallbacks

Todos los jueces tienen fallback `partial` en caso de error de API o fallo de parsing. El descompositor tiene fallback heurístico. El meta-juez devuelve `review_required` en caso de fallo. Ningún fallo parcial bloquea el pipeline — los LDPs con fallos se marcan para revisión humana.

---

## Consecuencias

- **Positivas:** Granularidad de evaluación por afirmación; detección temprana de jueces mal calibrados (kappa bajo); trazabilidad completa del razonamiento de cada juez.
- **Negativas:** Coste por run (3× LLM calls por LDP); latencia adicional en el pipeline nightly; mantenimiento de prompts de jueces.
- **Neutras:** Los LDP `review_required` requieren proceso de revisión humana; se define en ADR 0014 pero no se automatiza en esta fase.
