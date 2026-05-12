# Módulo de Derecho Comparado

Este documento describe el módulo `analisis_comparativo` de lex-agents (ADR 0027). Permite obtener una tabla pivot estructurada cuando una consulta cruza ≥ 2 jurisdicciones, en lugar de prosa integrada.

---

## Cuándo usarlo

Activa el modo comparativo si la consulta requiere **comparar explícitamente** los mismos aspectos jurídicos entre distintos ordenamientos:

- Transferencia internacional de datos (ES, EU, BR)
- Apertura de filial bancaria en varias jurisdicciones (ES, MX)
- Evaluación de riesgo PBC/FT multi-jurisdiccional (ES, BR, MX)
- Comparativa post-Brexit de cláusulas de jurisdicción (ES, EU, UK)

Para análisis centrados en una sola jurisdicción, usa `output_type=dictamen` (modo por defecto).

---

## Activación

### API

```json
POST /api/v1/consult
{
  "query": "...",
  "output_type": "analisis_comparativo",
  "jurisdictions": ["ES", "EU", "BR"]
}
```

### Frontend

1. Selecciona ≥ 2 jurisdicciones con los chips de jurisdicción.
2. Elige "Análisis comparativo" en el selector de tipo de output.
3. La UI mostrará automáticamente la `ComparativeView` con la tabla pivot.

---

## Estructura del output

El campo `comparative_output` de `ConsultResponse` contiene:

| Campo | Descripción |
|---|---|
| `issue` | Pregunta comparativa sintetizada |
| `jurisdictions_compared` | Lista de códigos ISO de jurisdicción |
| `dimensions` | Lista de dimensiones jurídicas (filas de la tabla) |
| `divergences` | Conflictos normativos identificados con severidad |
| `common_ground` | Principios que aplican igual en todas las jurisdicciones |
| `risk_differential` | Nivel de riesgo por jurisdicción (`low/medium/high`) |
| `risk_rationale` | Justificación del diferencial de riesgo |
| `coverage_gaps` | Jurisdicciones con cobertura parcial o insuficiente |
| `citations` | Citas renumeradas secuencialmente |
| `verification_status` | `green / amber / red` |

Cada **dimensión** tiene una entrada por jurisdicción con:
- `text`: análisis textual (null si cobertura insuficiente)
- `refs`: índices `[REF:n]` aplicables
- `coverage`: `full | partial | insufficient`
- `note`: advertencia o recomendación (ej. consultar asesoría local)

---

## Cobertura por jurisdicción

| Jurisdicción | Estado | Fuentes indexadas |
|---|---|---|
| ES | FULL | BOE (Boletín Oficial del Estado) |
| EU | FULL | EUR-Lex, AEPD, EDPB, EBA, ESMA |
| UK | PARTIAL | legislation.gov.uk, FCA (post-Brexit, en evolución) |
| BR | PARTIAL | INLABS-DOU (cobertura LGPD parcial) |
| MX | PARTIAL | SIDOF-DOF (CNBV parcialmente indexado) |
| PL | FULL | EUR-Lex (directivas transpuestas) |
| PT | FULL | EUR-Lex (directivas transpuestas) |
| AR, DE, CH, US | INSUFICIENTE | No indexadas en v0.2.0 |

`PARTIAL` implica que el sistema declara la limitación en `coverage_gaps` y recomienda verificación por asesoría local. **Nunca se inventa contenido para cobertura insuficiente.**

---

## Vista en el frontend

La `ComparativeView` organiza el output en cinco pestañas:

1. **Tabla comparativa** — pivote filas=dimensiones, columnas=jurisdicciones. Las celdas con cobertura insuficiente aparecen en ámbar. Hacer clic en cualquier celda abre un panel lateral con el texto completo y las citas.
2. **Divergencias** — tarjetas con descripción, jurisdicciones involucradas y severidad (`Baja / Media / Alta`).
3. **Terreno común** — principios equivalentes en todas las jurisdicciones comparadas.
4. **Riesgo diferencial** — tarjetas de riesgo por jurisdicción con rationale completo.
5. **Lagunas** — solo visible si hay `coverage_gaps`, con el motivo y la recomendación por jurisdicción.

---

## Exportación XLSX

El botón **↓ Exportar XLSX** en la vista de respuesta llama a:

```
GET /api/v1/consult/{trace_id}/export/comparative
```

El fichero generado contiene cuatro hojas:
- **Análisis comparativo** — tabla pivot con formato condicional por cobertura
- **Divergencias** — lista con severidad codificada por color
- **Riesgo diferencial** — tabla + rationale completo
- **Citas** — todas las referencias con fragmento original

Requiere autenticación JWT.

---

## Limitaciones conocidas

1. **Solo activable con `output_type=analisis_comparativo`** — el sistema no infiere automáticamente el modo comparativo. La detección automática de jurisdicciones (`planner_output.jurisdictions`) sí ocurre, pero el modo comparativo requiere indicación explícita.
2. **Máx. 5 jurisdicciones por consulta** — limitación de la API y del contexto del modelo.
3. **Las citas de la tabla pivot son las mismas citas recuperadas por el retriever** — el sistema no realiza búsquedas adicionales por dimensión.
4. **BR y MX en estado AMBER** — la cobertura de LGPD (Brasil) y CNBV/LIC (México) es parcial. Revisar siempre con asesoría local.
5. **El output es un borrador asistido por IA** — requiere validación por juristas especializados en cada ordenamiento antes de cualquier uso externo.

---

## Referencias

- [ADR 0027 — Comparative Law Module](decisions/0027-comparative-law-module.md)
- [Prompt sintesis_comparative v1](prompts/sintesis_comparative/v1.md)
- [Evals: casos comparativos COMP-001 a COMP-004](../evals/golden_dataset/)
