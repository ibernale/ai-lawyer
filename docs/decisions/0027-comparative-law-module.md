---
adr: "0027"
title: "Comparative Law module"
date: 2026-05-11
status: accepted
deciders: [ibernale]
phase: "7.0"
---

# ADR 0027 — Comparative Law module

## Contexto

Desde la fase 6.3 el sistema soporta consultas multi-jurisdicción mediante
`CrossJurisdictionCoordinator`: el Planner delega en especialistas en paralelo
y el resultado se agrega como respuesta narrativa. Ese modelo es suficiente
para preguntas generales del tipo "¿qué dice cada jurisdicción sobre X?".

Los usuarios de cumplimiento bancario necesitan frecuentemente un análisis
comparativo estructurado: cuáles son las divergencias regulatorias concretas
entre dos o más jurisdicciones, cuál genera mayor riesgo operativo, qué gaps
de cobertura existen. La respuesta narrativa agregada no satisface ese caso
de uso.

## Decisión

### 1. Trigger de activación

El modo `comparative` se activa cuando el `LegalPlanner` detecta
simultáneamente:

- `jurisdictions` contiene ≥ 2 jurisdicciones, **y**
- la rama principal está presente en ≥ 2 de esas jurisdicciones con cobertura
  suficiente (no `coverage_gap`).

El Planner incluye `mode: "comparative"` en la `PlannerOutput`. Si alguna
jurisdicción tiene cobertura insuficiente, el modo puede activarse igualmente
pero con `coverage_gaps` explícitos en el output (nunca se inventan contenidos
para esas celdas).

### 2. Cambio respecto al Coordinator de fase 6

El `CrossJurisdictionCoordinator` existente sigue ejecutando los especialistas
en paralelo. El cambio es el paso siguiente: en lugar de agregar las
respuestas en prosa, se añade un `ComparativeSynthesizer` que:

1. Recibe los `SpecialistResult` de cada jurisdicción.
2. Identifica las dimensiones de comparación relevantes (extraídas de la query
   o predefinidas por rama).
3. Produce un objeto `ComparativeAnalysis` con schema estructurado.

El `ComparativeSynthesizer` usa `claude-haiku-4-5` para la síntesis (coste
reducido; la riqueza normativa ya viene de los especialistas).

### 3. Schema `ComparativeAnalysis`

```json
{
  "issue": "Descripción del problema comparado",
  "jurisdictions_compared": ["ES", "EU", "UK"],
  "dimensions": [
    {
      "name": "Nombre de la dimensión comparada",
      "by_jurisdiction": {
        "ES": {
          "text": "Descripción para ES",
          "refs": ["[REF:1]", "[REF:2]"]
        },
        "EU": {
          "text": "Descripción para EU",
          "refs": ["[REF:3]"]
        },
        "UK": {
          "text": "Cobertura insuficiente. Consultar asesoría local.",
          "refs": [],
          "coverage_gap": true
        }
      }
    }
  ],
  "divergences": [
    "Texto describiendo una divergencia material entre jurisdicciones"
  ],
  "common_ground": [
    "Texto describiendo elementos comunes"
  ],
  "risk_differential": {
    "ES": "low",
    "EU": "medium",
    "UK": "unknown",
    "rationale": "Justificación breve del diferencial de riesgo"
  },
  "coverage_gaps": [
    "UK: cobertura de fuentes insuficiente para análisis completo"
  ]
}
```

**Regla estricta sobre `coverage_gap`**: cuando una celda no tiene chunks
RAG suficientes para la dimensión en esa jurisdicción, el campo `text` debe
ser exactamente `"Cobertura insuficiente. Consultar asesoría local."` y
`coverage_gap: true`. El LLM no puede rellenar celdas con conocimiento
paramétrico — solo con chunks recuperados.

### 4. Renderizado frontend

El frontend recibe `branch_answers` (respuesta narrativa por rama, fase 6)
y, cuando está presente, `comparative_analysis` (schema anterior).

Si `comparative_analysis` está presente, `ResponseView` renderiza:

- **Tabla pivot**: filas = dimensiones, columnas = jurisdicciones.
- Celdas de cobertura insuficiente: fondo gris, texto en cursiva, sin chips
  de referencia.
- Celdas con citas: chips `[REF:n]` clickables (flujo existente).
- Sección "Divergencias" debajo de la tabla: lista numerada.
- Sección "Terreno común": lista numerada.
- Sección "Diferencial de riesgo": tabla compacta con semáforo.
- Las celdas son expandibles (collapsible) para mostrar el texto completo.

La respuesta narrativa agregada (fase 6) sigue disponible como pestaña
alternativa para usuarios que prefieren prosa.

### 5. Casos canónicos que la implementación debe cubrir

| Caso | Ramas | Jurisdicciones |
| ---- | ----- | -------------- |
| Transferencia internacional de datos personales | `datos_personales_rgpd` | ES, EU, UK, BR |
| Apertura de filial bancaria | `regulatorio_bancario_ue_es` | ES, MX |
| Sanción administrativa PBC/FT | `penal_economico`, `administrativo` | ES, BR, MX |
| Cláusula de jurisdicción post-Brexit | `mercantil_societario` | ES, UK |

Estos casos deben incluirse como tests de integración en `evals/comparative/`
con fixtures de chunks y output esperado verificable.

### 6. Dimensiones predefinidas por rama

Para acelerar la síntesis y mejorar la coherencia, el `ComparativeSynthesizer`
usa un catálogo de dimensiones predefinidas por rama:

| Rama | Dimensiones canónicas |
| ---- | --------------------- |
| `datos_personales_rgpd` | Base legal del tratamiento, Derechos del interesado, Transferencias internacionales, Sanciones máximas, Autoridad supervisora |
| `regulatorio_bancario_ue_es` | Requisitos de capital, Liquidez (LCR/NSFR), Gobierno interno, Supervisión prudencial, Resolución |
| `mercantil_societario` | Ley aplicable al contrato, Jurisdicción de litigios, Forma de constitución, Responsabilidad socios |
| `penal_economico` | Responsabilidad penal persona jurídica, Umbral típico, Prescripción, Autoridad |

Si la query no encaja en el catálogo, el `ComparativeSynthesizer` infiere
las dimensiones relevantes del análisis de los especialistas.

## Alternativas consideradas

**Prosa agregada mejorada (fase 6)** — insuficiente para comparación precisa;
el usuario no puede extraer divergencias concretas sin leer toda la respuesta.

**Tabla hardcodeada por caso de uso** — rechazada porque la variabilidad de
queries es alta. El schema estructurado + dimensiones predefinidas es el
equilibrio entre flexibilidad y coherencia.

**Activar siempre que haya ≥ 2 jurisdicciones** — rechazado. Algunas queries
multi-jurisdicción son preguntas generales que no requieren comparación formal
("¿qué dice la ley laboral en ES y en UK?"). El trigger por `mode: comparative`
lo decide el Planner con base en la complejidad percibida.

## Consecuencias

- Nuevo `ComparativeSynthesizer` en `packages/agents/src/.../core/`.
- Nuevo tipo `ComparativeAnalysis` en el schema compartido.
- `ConsultResponse` gana campo opcional `comparative_analysis`.
- El frontend gana el componente tabla pivot con celdas expandibles.
- Los casos canónicos se añaden como evals en `evals/comparative/`.
- La cobertura LatAm (BR, MX, AR) es parcialmente limitada en fase 7;
  los `coverage_gaps` son la forma honesta de comunicarlo.
