# Guía de ingesta

## Arquitectura

```
Source (ABC)
├── BoeSource          ← API XML oficial BOE
└── EurlexSource       ← Cellar REST + SPARQL EUR-Lex
         │
         ▼
    RawDocument
         │
         ▼
    CanonicalDocument
         │
    LegalChunker  ──────────────────── Chunk[]
         │
    Contextualizer (Haiku + prompt cache) ─── Chunk[] (context_text)
         │
    BgeM3Embedder ───────────────────── EmbeddingResult[]
         │
    QdrantIndexer ───────────────────── Qdrant collection
```

## Ejecutar una ingesta de muestra

```bash
make ingest-sample          # BOE-A-2014-6732 + 32013R0575 (fixtures locales)
make ingest-real            # Fuentes reales (requiere ANTHROPIC_API_KEY + Qdrant)
```

## Añadir una fuente nueva

1. Implementa `Source(ABC)` en `packages/ingest/src/lex_agents_ingest/sources/<nombre>.py`:

   ```python
   class MiFuente(Source):
       source_id = "mi_fuente"
       rate_limit_rps = 0.5

       async def list_documents(self) -> list[str]: ...
       async def fetch(self, doc_id: str) -> RawDocument: ...
       def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument: ...
   ```

2. Captura fixtures para los tests (ver sección siguiente).

3. Escribe tests en `packages/ingest/tests/test_<nombre>.py` usando `respx`
   para mockear las llamadas HTTP. Los tests **nunca** hacen peticiones reales.

4. Añade la fuente al subagente `source-ingester` en `.claude/agents/source-ingester.md`.

## Estructura de fixtures

```
packages/ingest/tests/fixtures/
├── boe/
│   ├── BOE-A-2014-6732.xml
│   └── BOE-A-2015-1510.xml
└── eurlex/
    ├── 32013R0575.xml
    └── 32013L0036.xml
```

Las fixtures son XMLs grabados una única vez desde la fuente oficial y
commiteados al repositorio. **Nunca se modifican automáticamente en CI.**

## Capturar una fixture nueva

```bash
python scripts/capture_fixture.py boe BOE-A-2023-XXXX
python scripts/capture_fixture.py eurlex 32022R0XXX
```

El script descarga el documento, lo guarda en `tests/fixtures/<source>/` y
muestra el checksum. Commítalo manualmente tras verificar el contenido.

## Variables de entorno para ingesta real

```bash
ANTHROPIC_API_KEY=sk-ant-...       # Para la contextualización (Haiku)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=                    # Opcional
```

## Delegación a subagente

Para implementar o extender scrapers usa el subagente `source-ingester`
(`.claude/agents/source-ingester.md`). Documentación de referencia:
ADR `docs/decisions/0006-source-strategy.md`.
