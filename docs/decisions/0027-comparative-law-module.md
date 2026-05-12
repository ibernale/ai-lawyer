# ADR 0027 — Comparative Law Module

**Estado:** Aceptado  
**Fecha:** 2026-05-12  
**Autores:** lex-agents team  
**Revisores:** Legal del Grupo, Compliance

---

## Contexto

El sistema en Fase 6 ejecuta múltiples especialistas en paralelo cuando una consulta cruza jurisdicciones y sintetiza sus respuestas en un único dictamen de prosa integrada. Este modo es correcto para análisis monojurisdiccional o cuando el usuario necesita una recomendación unificada.

Sin embargo, para consultas que requieren **comparación explícita** entre sistemas jurídicos (ej. transferencia de datos ES-EU-BR, apertura de filial bancaria ES-MX, sanción PBC/FT ES-BR-MX), la prosa integrada oculta las diferencias y dificulta la toma de decisiones. El usuario necesita ver, para cada dimensión jurídica relevante, qué dice cada ordenamiento, dónde hay divergencias y dónde hay terreno común.

---

## Decisión

Se introduce un modo de output dedicado `analisis_comparativo` que:

1. **No mezcla** el análisis comparativo con el análisis monojurisdiccional. Son modos distintos, activados por:
   - Explícito: `output_type=analisis_comparativo` en la request
   - Implícito: el Planner detecta `len(jurisdictions) >= 2` con jurisdicciones de distintos ordenamientos (EU + nacional, o dos nacionales distintos)

2. Produce un `ComparativeResponse` estructurado (JSON), no prosa libre.

3. Cada celda de la tabla comparativa lleva `[REF:n]` verificables. La cobertura insuficiente se declara explícitamente (`coverage: "insufficient"`), nunca se inventa.

4. Las divergencias normativas se identifican en una sección propia con severidad (`low`/`medium`/`high`).

5. El `risk_differential` por jurisdicción lleva `rationale` obligatorio.

---

## Schema

```python
class ComparativeResponse(BaseModel):
    issue: str                                      # Pregunta comparativa sintetizada
    jurisdictions_compared: list[str]               # ["ES", "EU", "BR"]
    dimensions: list[ComparativeDimension]          # Filas de la tabla pivot
    divergences: list[Divergence]                   # Conflictos identificados
    common_ground: list[str]                        # Principios comunes
    risk_differential: dict[str, RiskLevel]         # {"ES": "low", "BR": "high"}
    risk_rationale: str                             # Explicación del diferencial
    coverage_gaps: list[CoverageGap]                # Jurisdicciones con cobertura parcial/insuficiente
    citations: list[CitationMapping]                # Citas renumeradas
    trace_id: str
    verification_status: Literal["green", "amber", "red"]

class ComparativeDimension(BaseModel):
    name: str                                       # Ej: "Transferencia internacional de datos"
    by_jurisdiction: dict[str, JurisdictionEntry]   # {"ES": ..., "EU": ..., "BR": ...}

class JurisdictionEntry(BaseModel):
    text: str | None     # None si cobertura insuficiente
    refs: list[int]      # Índices [REF:n] aplicables a esta celda
    coverage: CoverageLevel  # "full" | "partial" | "insufficient"
    note: str | None     # Ej: "Consultar asesoría local LGPD"

class Divergence(BaseModel):
    dimension: str
    description: str
    jurisdictions_involved: list[str]
    severity: RiskLevel  # "low" | "medium" | "high"

class CoverageGap(BaseModel):
    jurisdiction: str
    reason: str          # Ej: "Fuente INLABS-DOU parcialmente indexada"
    recommendation: str  # Ej: "Consultar asesoría local especializada en LGPD"
```

---

## Flujo de activación

```
ConsultRequest(output_type="analisis_comparativo")
    → OrchestratorV2 detecta modo comparativo
    → LegalPlanner produce PlannerOutput con output_type="analisis_comparativo"
    → CrossJurisdictionCoordinator.run_parallel() (sin cambios)
    → ComparativeSynthesizer.synthesize(responses, planner_output)
        → llama LLM con comparative_v1 prompt
        → parsea JSON → ComparativeResponse (Pydantic)
        → fallback si JSON inválido
    → ConsultResponse.comparative_output = ComparativeResponse
    → API serializa comparative_output
    → Frontend renderiza ComparativeView (tabla pivot)
```

---

## Restricciones

- **Mínimo 2 jurisdicciones**: si solo hay 1 jurisdicción, el modo comparativo no se activa; se usa el flujo estándar.
- **Máximo 5 jurisdicciones**: límite heredado del validador de `jurisdictions`.
- **Cobertura parcial permitida**: BR y MX tienen fuentes parciales (INLABS-DOU, SIDOF-DOF estado AMBER). El comparativo puede incluirlas con `coverage: "partial"` y `CoverageGap` explícito.
- **No auto-merge con prosa**: `ComparativeResponse` va en `ConsultResponse.comparative_output`; el campo `answer` contiene un resumen textual corto para compatibilidad con clientes que no consuman el JSON.
- **Verificación**: las citas `[REF:n]` dentro de cada `JurisdictionEntry.refs` pasan por `VerifierPipeline` igual que en el modo estándar.

---

## Jurisdicciones comparables en v1

| Jurisdicción | Cobertura | Fuentes                  |
| ------------ | --------- | ------------------------ |
| EU           | Full      | EUR-Lex, EDPB, EBA, ESMA |
| ES           | Full      | BOE, AEPD, BdE           |
| UK           | Partial   | legislation.gov.uk, FCA  |
| BR           | Partial   | INLABS-DOU (AMBER)       |
| MX           | Partial   | SIDOF-DOF (AMBER)        |

---

## Alternativas rechazadas

- **Prosa con tabla markdown**: el LLM tiende a omitir celdas vacías sin declararlas. El JSON forzado garantiza que cada celda tiene un `coverage` explícito.
- **Especialista de derecho comparado separado**: añadiría latencia sin valor; los especialistas existentes ya tienen el análisis por jurisdicción. El synthesizer comparativo agrega sobre sus outputs.
- **Activación solo explícita**: el Planner ya detecta jurisdicciones múltiples; aprovechar esa señal mejora la UX sin requerir que el usuario conozca el parámetro.

---

## Consecuencias

- `ConsultResponse` gana campo opcional `comparative_output: ComparativeResponse | None`
- `output_type` acepta nuevo valor `analisis_comparativo`
- `ComparativeSynthesizer` es la única ruta para producir `ComparativeResponse`; no hay otra forma de llegar a ese tipo
- El frontend muestra `ComparativeView` en lugar de `ResponseView` principal cuando `comparative_output` está presente
- La exportación XLSX está disponible exclusivamente para respuestas comparativas

---

## Implementación

**Fase 7.3** — implementación completa (ver PR correspondiente).
