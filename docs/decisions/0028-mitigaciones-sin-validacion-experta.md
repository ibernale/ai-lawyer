---
adr: "0028"
title: "Mitigaciones sin validación experta"
date: 2026-05-11
status: accepted
deciders: [ibernale]
phase: "7.0"
---

# ADR 0028 — Mitigaciones sin validación experta

## Contexto

Dos decisiones de diseño heredadas crean una tensión que se amplifica en
la fase 7:

1. El sistema genera borradores jurídicos asistidos por IA sin validación
   por juristas externos (gate F7-D del roadmap pendiente de contratar tiempo
   de jurista).
2. La fase 7 incorpora contenido jurisprudencial (ADR 0024), lo que aumenta
   el riesgo de error con consecuencias más graves para el usuario.

Este ADR fija el conjunto de mitigaciones que permiten operar en fase 7 con
ese riesgo asumido y visible, en lugar de enmascararlo.

## Decisión

### 1. Banner de advertencia reforzado

El banner ya existente ("Borrador asistido por IA") se reemplaza por el
siguiente texto, siempre visible en la parte superior de cada respuesta:

> **Sistema MVP — fase 7. Sin validación por jurista cualificado externo.**
> Esta respuesta es un borrador generado por IA que requiere verificación
> humana antes de cualquier uso operativo. Las citas jurisprudenciales son
> especialmente sensibles: confirme número de recurso, sala y vigencia del
> criterio antes de invocarlas.

El banner se muestra:
- **Siempre**, independientemente de la rama o el depth.
- Con fondo ámbar y borde izquierdo visible.
- No es descartable por el usuario (no tiene botón de cerrar).

Cuando `citation_type = "jurisprudencia"` está presente en la respuesta, se
muestra adicionalmente el banner específico de jurisprudencia definido en
el ADR 0024.

### 2. Feedback rápido por respuesta

Cada respuesta muestra tres botones de valoración inmediata:

| Botón | Valor almacenado |
| ----- | ---------------- |
| ✓ Aceptable | `acceptable` |
| ? Dudoso | `uncertain` |
| ✗ Incorrecto | `incorrect` |

Al marcar `uncertain` o `incorrect`, se abre un campo libre opcional (máx.
500 caracteres) para que el usuario describa el problema.

**Almacenamiento**: tabla `response_feedback` en SQLite (mismo fichero que
el historial de consultas), con columnas:
`(trace_id, feedback_value, comment, created_at, branch, depth, has_jurisprudencia)`.

**Uso**: el reflection agent (ADR 0021) prioriza casos con
`feedback_value IN ('uncertain', 'incorrect')` para análisis de fallos y
propuestas de mejora de prompt.

**Privacidad**: el campo `comment` se trata como dato potencialmente sensible;
no se loguea en texto claro ni se incluye en trazas de observabilidad.

### 3. Auditoría diaria por muestreo

Un job diario (Dagster sensor o cron) selecciona aleatoriamente 5 respuestas
del día para revisión manual:

- **Estratificación**: ≥1 por `depth` si hay volumen; ≥1 con
  `has_jurisprudencia = true` si las hubo.
- **Estados del ciclo de revisión**: `pending → reviewing → reviewed`.
  El campo `reviewer_notes` almacena las observaciones del revisor.
- **Página `/auditoria`**: accesible solo con rol `auditor`. Muestra la
  lista de respuestas en estado `pending` con el texto completo y las
  citas, sin revelar quién fue el usuario (campo `user_id` omitido en
  la vista).
- **No bloqueante**: la auditoría no afecta la latencia ni la disponibilidad
  del sistema. Es una capa de supervisión asíncrona.

Casos con `reviewed = incorrect` en auditoría se añaden a la cola de
prioridad del reflection agent junto con los casos de feedback negativo.

### 4. Lista de consultas no soportadas

El sistema reconoce las siguientes categorías de consultas como fuera de
su capacidad actual y devuelve una respuesta degradada:

| Categoría | Señal de detección | Respuesta degradada |
| --------- | ------------------ | ------------------- |
| Asesoramiento jurídico final | "puedo firmar", "debo aceptar", "es válido para mi caso" | Ver texto abajo |
| Cuestión procesal con plazo activo | "plazo vence", "recurso de apelación", "plazo de oposición" | Ver texto abajo |
| Cuantificación de daños o multas | "cuánto pagaré", "importe de la sanción", "calcule la multa" | Ver texto abajo |
| Estrategia procesal o de defensa | "cómo defenderme", "qué alegación presentar", "estrategia del juicio" | Ver texto abajo |
| Cumplimiento de obligación con autoridad | "puedo incumplir", "cómo evitar la sanción" | Ver texto abajo |

Texto de respuesta degradada (común para todas las categorías):

> *Esta consulta requiere asesoramiento jurídico cualificado que este sistema
> no puede proporcionar. El sistema solo ofrece contexto normativo general.*
>
> [Contexto normativo general relacionado con la pregunta, sin recomendación
> concreta de actuación.]

La detección se realiza con una lista de patrones en el router (antes del
especialista) complementada con una comprobación LLM Haiku de bajo coste.
La detección es conservadora: ante duda, el sistema proporciona el contexto
general con la advertencia, sin bloquear la respuesta.

La lista completa y actualizada se mantiene en `docs/legal/limitations.md`
(fichero ya existente).

### 5. Priorización del reflection agent

El reflection agent (ADR 0021) recibe casos en orden de prioridad:

1. Feedback `incorrect` + `has_jurisprudencia = true`.
2. Auditoría `reviewed = incorrect`.
3. Feedback `incorrect` (sin jurisprudencia).
4. Feedback `uncertain` + `has_jurisprudencia = true`.
5. Feedback `uncertain` (sin jurisprudencia).
6. Casos sin feedback (muestreo aleatorio).

Esta priorización garantiza que los fallos más graves (citas jurisprudenciales
incorrectas) se detecten y corrijan primero.

## Alternativas consideradas

**Bloquear respuestas hasta tener validación experta** — rechazado. Sin
funding para contratar tiempo de jurista en fase 7, el bloqueo detiene el
proyecto indefinidamente. Las mitigaciones técnicas son el sustituto temporal.

**Banner descartable por usuario** — rechazado. Un banner que el usuario
puede cerrar deja de ser una advertencia efectiva. El riesgo legal de
presentar el sistema como validado es mayor que el coste UX de un banner
persistente.

**Feedback con escala de 5 estrellas** — rechazado por ambigüedad. Tres
valores discretos (`aceptable/dudoso/incorrecto`) producen señal de
priorización más clara para el reflection agent.

## Consecuencias

- El componente `ResponseView` actualiza el banner a la versión reforzada.
- Nuevo componente de feedback (3 botones + campo libre) en `ResponseView`.
- Nueva tabla `response_feedback` en SQLite.
- Nueva página `/auditoria` en el frontend (protegida por rol `auditor`).
- El router incorpora la detección de consultas no soportadas.
- El reflection agent (ADR 0021) actualiza su cola de prioridades.
- `docs/legal/limitations.md` se convierte en la fuente canónica de
  categorías no soportadas (ya existe, se actualiza con las 5 categorías).
