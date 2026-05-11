---
adr: "0026"
title: "Document Agents arquitectura"
date: 2026-05-11
status: accepted
deciders: [ibernale]
phase: "7.0"
---

# ADR 0026 — Document Agents arquitectura

## Contexto

Hasta v0.2.0 el sistema solo responde consultas sobre normativa indexada
previamente en Qdrant. Los usuarios necesitan poder adjuntar documentos propios
(contratos, requerimientos del supervisor, circulares internas) y obtener
análisis jurídico sobre ellos en combinación con la base normativa RAG.

Este ADR define la arquitectura del pipeline de procesamiento documental.
El diseño parte de dos restricciones no negociables:

1. **Privacidad**: los documentos subidos pueden contener información
   confidencial o datos personales. No deben persistirse más allá de la
   consulta.
2. **Fidelidad estructural**: los documentos jurídicos tienen jerarquías
   (artículos, cláusulas, considerandos, fundamentos jurídicos) que el chunking
   RAG estándar destruye. El pipeline debe preservar esa jerarquía.

## Decisión

### 1. Pipeline completo

```
Upload ──► Format Detection ──► Parser ──► Segmentation
                                               │
                                     Entity Extraction
                                               │
                                    Specialist Analysis
                                    (RAG chunks + segments)
                                               │
                                        Verification
                                               │
                                           Output
```

Cada etapa es un paso síncrono dentro de la petición HTTP. No hay colas
asíncronas en fase 7 (los documentos de ≤200 páginas se procesan en tiempo
aceptable).

### 2. Límites duros

| Parámetro         | Límite    | Acción si se supera                        |
| ----------------- | --------- | ------------------------------------------ |
| Tamaño fichero    | 50 MB     | HTTP 413 con mensaje claro antes de parsear |
| Páginas PDF       | 200       | HTTP 422 con instrucción de dividir el documento |
| Documentos/request | 1        | HTTP 422 (soporte multi-doc queda para fase 8) |

### 3. Matriz de parsers

| Formato | Parser primario | Parser fallback | Notas |
| ------- | --------------- | --------------- | ----- |
| PDF (texto nativo) | PyMuPDF4LLM | Marker (con OCR) | Fallback si layout score < 0.7 o tablas detectadas |
| PDF crítico (flag `alta_fidelidad`) | Claude Opus vía base64 | — | Solo si documento < 100 páginas; coste ~$0.15/doc |
| DOCX | python-docx | — | Preserva headings, listas, tablas |
| TXT | chardet + UTF-8 | — | Detección de encoding obligatoria |
| EML | email stdlib + mailparser | — | Adjuntos procesados recursivamente con su parser |

El flag `alta_fidelidad` lo activa el usuario desde el frontend. Se muestra
advertencia de coste antes de confirmar.

**Criterio de selección PDF → Marker fallback**: PyMuPDF4LLM produce un
`layout_confidence_score`. Si `score < 0.70` o si el documento contiene tablas
con celdas fusionadas (detectadas por número de columnas inconsistente por
página), se relanza con Marker. El resultado de Marker siempre se usa si el
primario falla con excepción.

### 4. Segmentación semántica (≠ chunking RAG)

La segmentación documental opera sobre unidades semánticas reconocibles en
documentos jurídicos:

| Tipo de documento      | Unidades semánticas |
| ---------------------- | ------------------- |
| Contrato               | Cláusulas numeradas, Considerandos, Anexos |
| Requerimiento supervisor | Hechos, Fundamentos, Parte dispositiva |
| Resolución administrativa | Antecedentes, Fundamentos jurídicos, Resolución |
| Circular interna       | Secciones por título H1/H2, párrafos numerados |

Cada segmento lleva metadatos: `{segment_id, segment_type, hierarchy_level,
page_start, page_end, char_start, char_end, heading_text}`.

La segmentación **no reemplaza** el chunking RAG: los segmentos son la
unidad de análisis para el especialista; los chunks RAG siguen siendo la
unidad de retrieval para la normativa externa.

### 5. Entity extraction

Se ejecuta sobre los segmentos, no sobre el documento completo:

- **Partes**: regex + LLM Haiku para extraer nombres, roles (arrendador,
  arrendatario, acreedor, deudor, etc.) y referencias cruzadas entre partes.
- **Normativa referenciada**: regex de patrones `(Ley|RD|Reglamento|Directiva)
  \d+/\d{4}` + LLM Haiku para confirmar y añadir artículos específicos.
- **Plazos**: patrones `\d+ (días|meses|años)` + fecha absoluta si aparece.
- **Obligaciones**: verbos deónticos (`deberá`, `queda obligado`, `se obliga`,
  `shall`, `must`) + sujeto + objeto.
- **Cláusulas críticas** (presencia/ausencia + localización):
  `penalty`, `jurisdiction`, `governing_law`, `termination`,
  `confidentiality`, `IP`, `force_majeure`, `indemnity`,
  `limitation_of_liability`, `change_of_control`.

El output de entity extraction se incluye en el contexto del especialista
como bloque estructurado adicional.

### 6. Dos tipos de cita en la respuesta

La respuesta del especialista puede referenciar dos fuentes distintas:

- `[REF:n]` — referencia a chunk RAG (normativa o jurisprudencia externa,
  según `citation_type` del ADR 0024).
- `[DOC:s]` — referencia a un segmento del documento subido por el usuario,
  identificado por `segment_id`.

El verificador existente se extiende para validar ambos tipos:
- `[REF:n]`: verificación contra chunk Qdrant (flujo existente).
- `[DOC:s]`: verificación contra el texto del segmento en memoria
  (mismo mecanismo semántico, sin Qdrant).

El frontend renderiza `[DOC:s]` con un chip de color distinto (verde vs.
azul para `[REF:n]`) que expande el texto del segmento inline.

### 7. Privacidad y no-persistencia

- El documento original (bytes) se mantiene en memoria durante el procesamiento
  y se descarta al finalizar la petición HTTP.
- Lo único que persiste en base de datos es:
  - `trace_id` (UUID de la consulta)
  - `doc_hash` (SHA-256 del documento, para deduplicación de auditoría)
  - `doc_summary` (resumen estructurado: tipo, páginas, entidades extraídas
    — sin contenido literal)
  - `processing_ms` (métrica de rendimiento)
- Los segmentos y entidades se pasan en el contexto de la petición y no se
  almacenan en Qdrant ni en ninguna base de datos.
- Los logs no incluyen fragmentos del documento (`structlog` con campo
  `doc_content = "[REDACTED]"`).

### 8. Interacción con el pipeline existente

El especialista recibe un contexto enriquecido:

```python
SpecialistContext(
    query=...,
    rag_chunks=[...],          # chunks Qdrant existentes
    document_segments=[...],   # segmentos del documento subido
    extracted_entities=...,    # entidades extraídas
    doc_metadata=...,          # tipo, páginas, hash
)
```

El prompt del especialista se adapta para indicar al LLM que tiene acceso a
ambas fuentes y que debe diferenciar citas `[REF:n]` de `[DOC:s]`.

## Alternativas consideradas

**Indexar el documento en Qdrant temporalmente** — rechazado por privacidad.
La gestión del TTL en Qdrant es compleja y el riesgo de retención accidental
es alto.

**Un único parser (Marker siempre)** — rechazado por coste y latencia. Marker
con OCR es 5–10× más lento que PyMuPDF4LLM para PDFs nativos. El fallback
selectivo equilibra velocidad y fidelidad.

**Multi-documento por request** — rechazado para fase 7. El contexto LLM
con varios documentos segmentados + RAG excede fácilmente la ventana de
contexto útil. Se reevalúa en fase 8 con selección de segmentos relevantes.

## Consecuencias

- Nuevo módulo `packages/agents/src/.../document_pipeline/` con los pasos
  del pipeline como clases independientes y componibles.
- Nuevas dependencias: `pymupdf4llm`, `marker-pdf` (opcional/lazy),
  `python-docx`, `chardet`, `mailparser`.
- Nuevo tipo `DocumentSegment` en el schema de tipos compartidos.
- El verificador gana método `verify_doc_citation(claim, segment)`.
- El frontend gana chip `[DOC:s]` de color verde con expansión inline.
- Los límites de 50 MB y 200 páginas se validan en el endpoint FastAPI
  antes de invocar el pipeline.
