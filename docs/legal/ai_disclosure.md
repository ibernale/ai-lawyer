# Divulgación sobre el uso de IA — lex-agents

> **Versión:** 0.1.0 · **Fecha:** 2026-05-11

---

## ¿Qué es este sistema?

**lex-agents** es una herramienta de asistencia jurídica basada en inteligencia
artificial generativa (modelos de lenguaje de gran escala de Anthropic). Su
propósito es ayudar a los equipos jurídicos internos a localizar y sintetizar
información normativa sobre regulación bancaria europea y española.

---

## Lo que el sistema hace

- Recupera fragmentos de textos normativos públicos (BOE, EUR-Lex) indexados
  localmente mediante un motor de búsqueda vectorial.
- Genera una respuesta en lenguaje natural citando los fragmentos recuperados.
- Verifica automáticamente que cada afirmación normativa esté respaldada por
  una cita en el texto recuperado.

## Lo que el sistema NO hace

- **No constituye asesoramiento jurídico.** Sus respuestas son borradores
  asistidos, no dictámenes legales.
- **No sustituye la revisión por un jurista cualificado.** Toda respuesta
  debe ser revisada y validada por un profesional del derecho antes de
  cualquier uso externo o toma de decisiones.
- **No garantiza exactitud.** Los modelos de IA generativa pueden producir
  afirmaciones incorrectas, incompletas o desactualizadas ("alucinaciones"),
  incluso cuando el verificador automático las clasifica como correctas.
- **No cubre jurisprudencia.** El índice actual no incluye sentencias del
  TJUE, Tribunal Supremo, Audiencia Nacional ni CENDOJ.
- **No está validado por expertos.** El dataset de evaluación
  (`evals/golden_dataset/`) tiene `expert_reviewed: false` en todos los casos.
  Ningún jurista ha validado formalmente los casos de prueba.

---

## Obligaciones del usuario

1. **Tratar toda respuesta como borrador.** Verificar las citas directamente
   en las fuentes originales (EUR-Lex, BOE) antes de citar o actuar.
2. **No compartir respuestas sin revisión jurídica previa.** En particular,
   no enviar a clientes, reguladores ni terceros sin validación humana.
3. **Reportar errores.** Usar el botón "Reportar problema" o el canal interno
   designado para notificar respuestas incorrectas o engañosas.
4. **No introducir datos personales** en las consultas. El sistema no está
   diseñado para procesar datos de clientes identificables.

---

## Limitaciones conocidas del modelo

- Conocimiento de entrenamiento con corte en agosto de 2025.
- El índice local puede no reflejar las últimas modificaciones normativas.
- Los prompts y el dataset de evaluación no han sido revisados formalmente
  por ningún jurista externo.
- El verificador automático reduce el riesgo de alucinaciones pero no lo
  elimina: una cita verificada como correcta puede seguir siendo parcial,
  malinterpretada o descontextualizada.

---

## Estado del sistema

**Sistema en fase MVP (v0.1.0), entorno local únicamente.**
No apto para uso en producción, entornos regulados ni decisiones
con consecuencias legales reales sin revisión interna formal previa.
