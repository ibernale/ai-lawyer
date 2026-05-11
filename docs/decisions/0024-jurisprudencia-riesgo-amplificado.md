---
adr: "0024"
title: "Riesgo amplificado por contenido jurisprudencial"
date: 2026-05-11
status: accepted
deciders: [ibernale]
phase: "7.0"
---

# ADR 0024 — Riesgo amplificado por contenido jurisprudencial

## Contexto

Hasta v0.2.0 el sistema cita exclusivamente fuentes normativas estructuradas
(BOE, EUR-Lex, BdE, EBA, ESMA, FCA). El error típico en ese modelo es citar mal
un artículo o un número de reglamento. El daño es corregible: el contenido
normativo es estable, público y verificable al instante por el usuario.

La sub-fase 7.1 incorpora fuentes jurisprudenciales (CENDOJ, Tribunal
Constitucional, DOU/DOF). Esto cambia cualitativamente el perfil de riesgo:

| Dimensión              | Fuente normativa          | Fuente jurisprudencial                              |
| ---------------------- | ------------------------- | --------------------------------------------------- |
| Error típico           | Artículo incorrecto       | Número de recurso, sala, ponente o fecha erróneos   |
| Gravedad de la cita    | Norma de aplicación general | Precedente de aplicación al caso concreto         |
| Verificabilidad        | Alta (texto oficial público) | Media (requiere acceso a la base jurisprudencial) |
| Confusión ratio/obiter | No aplica                 | Alta — el modelo puede confundir obiter con ratio   |
| Impacto si erróneo     | El usuario lo detecta     | Puede inducir una estrategia jurídica incorrecta    |

## Decisión

### 1. Campo `citation_type` en `CitationMapping`

Se añade `citation_type: Literal["normativa", "jurisprudencia"]` a la clase
`CitationMapping` (en `packages/agents/src/.../types.py` o equivalente).
El campo se propaga desde el metadata del chunk en Qdrant (`citation_type`
payload field). Los chunks de CENDOJ/TC/DOU/DOF se indexan con
`citation_type = "jurisprudencia"`; el resto conserva `"normativa"`.

Esta distinción permite que verificador y frontend actúen de forma diferente
según el tipo de fuente.

### 2. Modo estricto del verificador para sentencias

Cuando el verificador procesa un claim que contiene `citation_type =
"jurisprudencia"`, aplica las siguientes reglas adicionales respecto al modo
normal:

- **Número de recurso**: si el claim menciona un número de recurso (patrón
  `\d+/\d{4}`), debe aparecer literalmente en el chunk recuperado. Sin match
  exacto → cita rechazada con estado `REJECTED_NO_CASE_NUMBER`.
- **Año**: si el claim menciona un año de sentencia, debe coincidir con el
  campo `year` del metadata del chunk.
- **Sala / Ponente**: si el claim los menciona, deben aparecer en el fragmento
  o en el metadata (`sala`, `ponente`). Si no aparecen en el chunk, el
  verificador no los incluye en la cita resultante — no los inventa.
- **Obiter / Ratio**: el verificador no distingue automáticamente ratio de
  obiter. Por ello, la respuesta generada incluye siempre la advertencia:
  "La cita recoge el fragmento recuperado; la distinción ratio/obiter
  requiere lectura íntegra de la resolución."
- **Umbral de similitud semántica**: subido de 0.75 → 0.85 para aceptar el
  fragmento como soporte del claim.

Si el verificador rechaza una cita jurisprudencial, el especialista recibe
feedback `CITATION_REJECTED` y debe declarar explícitamente la ausencia de
base verificada en lugar de reformular la cita.

### 3. Umbral LeMAJ para respuestas con jurisprudencia

Cuando la respuesta contiene al menos una `CitationMapping` con
`citation_type = "jurisprudencia"`, el LeMAJ aplica umbrales más estrictos:

| Métrica                 | Umbral estándar | Umbral jurisprudencia |
| ----------------------- | --------------- | --------------------- |
| `ldp_unsupported_rate`  | ≤ 0.10          | ≤ 0.05                |
| `review_required`       | `score < 0.70`  | `score < 0.75`        |

Una respuesta con `ldp_unsupported_rate > 0.05` en modo jurisprudencia produce
estado `LeMAJ = AMBER` como mínimo, independientemente del score global.

### 4. Banner reforzado en frontend

Cuando `response.citations` contiene al menos un elemento con
`citation_type = "jurisprudencia"`, el componente `ResponseView` muestra un
banner de advertencia adicional (color ámbar, icono ⚠️) con el texto exacto:

> **Respuesta con citas jurisprudenciales.** Los fragmentos recuperados son
> extractos parciales. La distinción entre ratio decidendi y obiter dictum, la
> aplicabilidad al caso concreto y la vigencia del criterio jurisprudencial
> requieren revisión por jurista cualificado.

El banner estándar de IA (ya existente) se mantiene independientemente.

### 5. Auditoría de muestreo

Se implementa un mecanismo de auditoría formal (página `/auditoria`) con las
siguientes características:

- **Frecuencia**: muestreo aleatorio de 5 respuestas/día.
- **Estratificación**: al menos 1 respuesta por `depth` (shallow/standard/deep)
  si hay volumen suficiente; al menos 1 respuesta con `citation_type =
  "jurisprudencia"` si hubo alguna ese día.
- **Estados**: `pending → reviewing → reviewed` con campo `reviewer_notes`.
- **No bloqueante**: la auditoría corre en background, no afecta la latencia
  de respuesta.
- **Impacto**: casos marcados como `reviewed = incorrecto` priorizan la cola
  del reflection agent (ver ADR 0021).

La implementación detallada de la página `/auditoria` queda para sub-fase 7.4.

## Alternativas consideradas

**No distinguir tipos de cita** — rechazada porque el verificador actual
asume que el chunk contiene texto normativo estable. Aplicarlo a sentencias
sin ajuste genera falsos positivos (el chunk tiene el fragmento pero sin
los metadatos estructurales necesarios).

**Bloquear respuestas con jurisprudencia hasta validación experta** — rechazada
como exceso de restricción en fase 7 dev. El banner + umbral LeMAJ estricto
es el equilibrio adecuado para el período sin validación experta.

## Consecuencias

- `CitationMapping` gana campo `citation_type` (cambio de schema, migración
  trivial — default `"normativa"`).
- El verificador gana un `strict_mode` activado automáticamente cuando
  detecta `citation_type = "jurisprudencia"`.
- El componente `ResponseView` gana lógica de banner condicional.
- Los umbrales LeMAJ se parametrizan por tipo de cita.
- Los ADR 0025 (CENDOJ), 0026 (Document Agents) y 0028 (Mitigaciones) se
  apoyan en las garantías definidas aquí.
