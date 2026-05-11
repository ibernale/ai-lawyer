# Limitaciones conocidas — lex-agents v0.1.0

> **Fecha:** 2026-05-11

Este documento recoge de forma transparente las limitaciones conocidas del
sistema en su estado MVP. **Leer antes de usar.**

---

## 1. Alucinaciones y errores factuales

Los modelos de lenguaje pueden generar afirmaciones normativas incorrectas,
incompletas o desactualizadas incluso cuando el texto recuperado parece
respaldarlas. El verificador automático (heurístico + LLM) reduce este riesgo
pero **no lo elimina**:

- Una cita marcada como `PASSED` puede ser correcta en apariencia pero
  malinterpretada o extraída fuera de contexto.
- El verificador no detecta omisiones: puede que la respuesta ignore un
  artículo relevante sin citarlo.
- Las afirmaciones sin `[REF:n]` (clasificadas como `uncited_claims`) pueden
  ser correctas pero no verificables automáticamente.

**Recomendación:** Verificar siempre las citas directamente en EUR-Lex o BOE.

---

## 2. Cobertura normativa limitada

El índice actual cubre únicamente:

| Norma | Cobertura |
|-------|-----------|
| CRR (Reg. 575/2013) | Parcial (arts. seleccionados) |
| CRD IV (Dir. 2013/36/UE) | Parcial |
| BRRD (Dir. 2014/59/UE) | Parcial |
| SRMR (Reg. 806/2014) | Parcial |
| AMLD5 (Dir. 2018/843/UE) | Parcial |
| Ley 10/2014 (ES) | Parcial |
| CRR2, CRR3, CRD5 | No indexados en MVP |
| DORA (Reg. 2022/2554) | No indexado |
| MiCA (Reg. 2023/1114) | No indexado |

**No indexado en MVP:** CENDOJ, Tribunal Supremo, TJUE, EBA Q&As, BdE Circulares,
normas de transposición autonómicas, legislación fiscal, laboral, penal o civil.

---

## 3. Dataset de evaluación no validado por experto

El dataset `evals/golden_dataset/` tiene `expert_reviewed: false` en **todos
los casos**. Los 30 casos fueron generados automáticamente como punto de
partida. Ningún jurista cualificado ha revisado ni firmado ningún caso.

Esto significa que los umbrales de CI (`citation_recall ≥ 0.7`, etc.) se
miden contra un benchmark no validado. Los números son orientativos, no
auditables.

---

## 4. Prompts no revisados formalmente

Los prompts en `docs/prompts/` fueron diseñados por el equipo de desarrollo.
No han sido sometidos a revisión formal por juristas especializados en
regulación bancaria. Pueden contener instrucciones subóptimas o incompletas.

---

## 5. No sustituye asesoramiento jurídico profesional

El sistema no es un despacho de abogados ni un sistema de dictamen legal.
Sus respuestas son borradores asistidos que requieren:
1. Verificación humana de las citas.
2. Análisis contextual por un jurista cualificado.
3. Consideración de la situación específica del cliente.

**Ninguna respuesta del sistema debe citarse directamente** en documentos
legales, regulatorios o contractuales sin revisión previa.

---

## 6. Normas en revisión activa

Varias normas cubiertas están sujetas a modificaciones en curso:

- **CRR3** (Reg. 2024/1623): Transitional arrangements, output floor,
  implementación escalonada hasta 2033.
- **DORA**: Aplicación plena desde enero 2025, pero guías técnicas EBA/ESMA
  en consulta pública.
- **Ley 10/2014**: Posibles modificaciones por transposición de CRD5.

Las fechas de publicación del índice (`ChunkMetadata.publication_date`)
son indicativas; verificar vigencia en la fuente original.

---

## 7. Restricciones técnicas del MVP

- **Sin multi-turno:** Cada consulta es independiente; no hay memoria de
  conversaciones anteriores.
- **Sin acceso a Internet:** El sistema no busca ni actualiza normas en
  tiempo real.
- **Sin reranker fine-tuneado:** El reranker usa `bge-reranker-v2-m3`
  genérico, no ajustado a terminología jurídica española.
- **Sin gestión de conflictos normativos:** Si dos normas se contradicen,
  el sistema puede no detectarlo.

---

## 8. Seguridad y privacidad

Ver [`docs/legal/privacy.md`](privacy.md) y [`docs/legal/ai_disclosure.md`](ai_disclosure.md).

En MVP: sin cifrado en reposo, sin multi-tenant, sin auditoría formal de accesos.
