# ADR 0040 — RAG en AWS: Bedrock Knowledge Bases + Aurora Serverless v2 + pgvector

**Estado:** Accepted  
**Fecha:** 2026-05-13  
**Decisores:** Ignacio Bernal (Santander)  
**ADRs relacionados:** 0003 (RAG architecture), 0006 (fuentes), 0017 (ingesta Dagster),
0036 (regiones), 0039 (Bedrock), 0041 (networking), 0042 (persistencia), 0043 (CDK)  
**Sub-fases afectadas:** 9.3 – 9.4

---

## Contexto

El stack RAG local usa Qdrant como vector store (colección `lex_legal_docs` con vectores
densos 1024-dim BGE-M3 + SPLADE sparse) y `HybridRetriever` en `packages/rag/`.
En producción AWS necesitamos:

1. **Managed vector store:** Qdrant self-hosted requiere operar un cluster; en banca con
   DORA preferimos infra gestionada.
2. **Coste contenido en Fase 9:** el volumen de documentos es bajo (~1.000 chunks en MVP).
   Pagar por instancia siempre encendida no se justifica.
3. **Cifrado + IAM:** KMS, in-VPC, IAM-based access, sin endpoint público.
4. **Preservar el chunking jurídico:** el `LegalChunker` (ADR 0003, `packages/ingest/`)
   es crítico para la calidad del RAG. No podemos usar el chunking estándar de Bedrock KB.
5. **Hybrid search:** denso + léxico, como en Qdrant.

---

## Decisión

### Vector store: Aurora Serverless v2 PostgreSQL + pgvector

Aurora Serverless v2 con la extensión `pgvector` y HNSW indexing como backend de vectores.

**Justificación específica:**
- **Escala casi a cero:** Aurora Serverless v2 puede pausarse automáticamente cuando no
  hay carga. En dev fuera de horario, el coste baja a ~$0 (solo almacenamiento).
  En prod, el ACU mínimo es 0.5 ACU (~$60/mes) sin instancia idle.
- **pgvector HNSW:** comparable a Qdrant HNSW para nuestro volumen (<100K chunks en MVP).
  La diferencia de latencia es <5 ms para queries vectoriales; irrelevante para consultas
  jurídicas que tardan segundos.
- **Infraestructura conocida:** Aurora es el servicio de BD relacional estándar de AWS para
  banca; los equipos de DBA de Santander tienen expertise. Menos superficie desconocida.
- **Datos consolidados:** Aurora ya aloja el resto del estado de la app (ADR 0042). El
  cluster compartido reduce coste y ops overhead.
- **KMS + VPC + IAM:** Aurora Serverless v2 cumple todos los requisitos de seguridad sin
  configuración adicional.

**Índice pgvector:**
```sql
-- Colección principal
CREATE TABLE legal_chunks (
    chunk_id    TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    jurisdiction TEXT,
    document_type TEXT,
    hierarchy_path TEXT,
    section_type TEXT,
    publication_date DATE,
    in_force_at_indexing BOOLEAN DEFAULT true,
    language    TEXT DEFAULT 'es',
    text        TEXT NOT NULL,
    embedding   vector(1024),          -- BGE-M3 dense
    sparse_embedding JSONB,            -- SPLADE sparse (token_id → weight)
    checksum    TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX legal_chunks_embedding_idx
    ON legal_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX legal_chunks_source_idx ON legal_chunks (source_id);
CREATE INDEX legal_chunks_jurisdiction_idx ON legal_chunks (jurisdiction);
```

### Bedrock Knowledge Bases con Custom Chunking

Amazon Bedrock Knowledge Bases gestiona el ciclo RAG completo (ingesta, embedding,
retrieval, re-ranking opcional). Adoptamos KB pero con **Custom Chunking** para preservar
el `LegalChunker`.

**Cómo funciona el Custom Chunking en KB:**
1. Bedrock KB detecta un nuevo documento en S3.
2. En lugar de aplicar chunking estándar, invoca un **Lambda Custom Chunking Hook**.
3. La Lambda ejecuta `LegalChunker` (de `packages/ingest/`) sobre el documento.
4. Devuelve los chunks a KB, que los embeda y los indexa en Aurora pgvector.

```
S3 raw (BOE XML, EUR-Lex XML)
    │
    ▼ (S3 event / Dagster trigger)
Bedrock KB ingestion job
    │
    ▼ Custom Chunking hook
Lambda: LegalChunker (packages/ingest/)
    │
    ▼
Bedrock KB → embed (ver sección embeddings) → Aurora pgvector
```

**Hybrid search en Bedrock KB:**
Bedrock KB con Aurora pgvector soporta hybrid search (vector + BM25) nativamente.
El `HybridRetriever` de `packages/rag/` se adapta para llamar a la KB API en lugar de
Qdrant directamente. La interfaz `SearchFilters` y el contrato de `Chunk` se mantienen.

### Embeddings: decisión pendiente en sub-fase 9.3

Hay dos opciones viables; la elección final se hace tras benchmark con el golden dataset
de evals en sub-fase 9.3:

#### Opción A (preferida): BGE-M3 en SageMaker Inference Endpoint serverless

- **Por qué preferida:** performance idéntica al modelo local. No requiere re-evaluar
  el golden dataset ni recalibrar umbrales del verifier.
- **Implementación:** imagen Docker con `sentence-transformers` + BGE-M3 en SageMaker
  Serverless Endpoint. Cold start ~3-5s (aceptable para ingesta batch; no para retrieval
  en tiempo real si el endpoint está frío).
- **Coste:** ~$40/mes a volumen dev (serverless = pago por inferencia, no por instancia).
- **Mitigación cold start en retrieval:** warm-up ping cada 5 min via EventBridge si el
  endpoint está en uso activo; auto-pause fuera de horario.

#### Opción B (fallback): Cohere Embed Multilingual v3 via Bedrock

- **Por qué es fallback:** nativamente integrado con Bedrock KB (sin SageMaker overhead);
  multilingüe; sin cold start. Trade-off: modelo diferente → requiere re-benchmark completo
  del golden dataset y re-calibrar umbrales de citación.
- **Coste:** ~$0.10 por 1M tokens (razonable a volumen dev).
- **Activar si:** el benchmark en 9.3 muestra que la degradación de calidad respecto a
  BGE-M3 es < 5% en citation_recall (umbral definido en evals/smoke).

### Reranker: BGE-Reranker-v2-m3 en SageMaker Serverless

Mismo modelo que en local (`BAAI/bge-reranker-v2-m3`), mismo patrón SageMaker Serverless
que los embeddings. Sin cambios en `packages/rag/reranker.py` excepto la URL del endpoint.

---

## Migración del índice Qdrant local

Proceso de migración para sub-fase 9.3:

1. **Export:** script `scripts/export_qdrant.py` → JSONL con `{chunk_id, text, embedding, sparse, metadata}`.
2. **Upload:** JSONL a S3 (`lex-agents-canonical-dev`).
3. **Re-ingest:** job de Bedrock KB sobre los JSONL (bypass custom chunking; vectores ya calculados).
4. **Validación:** ejecutar eval suite completo contra el nuevo KB. Aceptar si `citation_recall ≥ 0.60` (umbral smoke).
5. **Cutover:** cambiar `RETRIEVER_BACKEND=bedrock_kb` en `workloads-dev`.
6. **Qdrant local:** mantener como fallback durante 2 semanas post-cutover, luego deprecar.

---

## Alternativas consideradas

### OpenSearch Serverless

| Criterio | OpenSearch Serverless | Aurora + pgvector |
|---|---|---|
| Coste mínimo | ~$700/mes (2 OCUs mínimo) | ~$60/mes (0.5 ACU) |
| Performance a escala | Superior (>1M chunks) | Suficiente (<100K chunks MVP) |
| Ops | Menos (managed) | Menos (shared cluster ya existente) |
| Bedrock KB integración | ✅ Soportado | ✅ Soportado |

**Decisión:** Aurora en Fase 9; OpenSearch Serverless documentado como upgrade path cuando
el corpus crezca a >500K chunks o cuando la latencia de retrieval sea inaceptable.

### S3 Vectors (nuevo servicio AWS 2025)

S3 Vectors es una capa de almacenamiento vectorial sobre S3, con pricing muy bajo.
Limitaciones para nuestro caso:
- Sin filtering avanzado por metadata (jurisdiction, in_force_at_indexing, etc.).
- Sin re-ranking integrado.
- Latencia de retrieval mayor que HNSW en-memoria.

**Posible uso futuro:** corpus BOE histórico (>10 años de legislación, millones de chunks)
donde el filtering avanzado no es crítico y el precio por vector domina.

### Pinecone / Weaviate (managed externos)

- Data residency en EEA no garantizada sin contrato específico para banca.
- Vendor lock-in adicional fuera del ecosistema AWS.
- Sin integración nativa con Bedrock KB.

---

## Trade-offs y consecuencias

| Trade-off | Impacto |
|---|---|
| `HybridRetriever` requiere adaptación | Cambio de Qdrant API a Bedrock KB API. Interfaz `SearchFilters` se mantiene. Estimación: 1 semana dev en 9.3. |
| Embeddings: decisión en 9.3 | Bloquea el cutover hasta benchmark. Mitigado: el índice Qdrant local sirve como fallback durante evaluación. |
| Custom Chunking Lambda | Nueva Lambda que empaqueta `packages/ingest/`. Añade latencia a ingesta (aceptable; ingesta es batch). |
| Aurora shared cluster | Contención posible si queries vectoriales pesadas coinciden con escrituras governance. Mitigado: ACU escala automáticamente; separar schemas. |
| SageMaker cold start | 3-5s primer request tras inactividad. Warm-up via EventBridge si el SLA de retrieval lo requiere. |
