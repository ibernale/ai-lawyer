# 0006 — Estrategia de Ingesta: APIs Oficiales sobre Scraping HTML

**Status:** Accepted
**Date:** 2026-05-10

## Context

lex-agents necesita ingerir normativa bancaria europea y española de forma
reproducible, estable y respetuosa con los términos de uso de las fuentes.
Existen dos estrategias generales: (a) acceso a APIs o endpoints oficiales de
datos abiertos, y (b) scraping HTML ad-hoc.

## Decision

### Principio: API oficial > scraping HTML

Siempre que una fuente oficial publique un API o endpoint de datos abiertos,
lex-agents lo usa en vez de scraping HTML. HTML es frágil ante cambios de
diseño; las APIs de datos abiertos tienen versionado semántico.

### Fuente BOE (España)

- **API XML oficial**: `https://boe.es/diario_boe/xml.php?id=<id>`
- Formato: XML estructurado con `<metadatos>`, `<texto>`, `<articulo>`,
  `<marginales>` y `<parrafo>`
- Licencia: datos abiertos (Real Decreto 806/2015)
- `BoeSource` implementa la interfaz `Source(ABC)`

### Fuente EUR-Lex (UE)

- **Cellar webservice**: `https://publications.europa.eu/resource/cellar/<id>`
- **SPARQL endpoint**: `https://publications.europa.eu/webapi/rdf/sparql`
- Resolución: CELEX ID → Cellar URI vía SPARQL, luego GET con `Accept: application/xml`
- Formatos soportados (por prioridad): Formex XML > XHTML
- PDF: **no soportado en Fase 2** — se registra warning y se ignora el documento
- `EurlexSource` implementa `Source(ABC)`

### Rate limiting

Ambas fuentes respetan un límite de **≤ 0.5 req/s** (1 solicitud cada 2s),
implementado en `RateLimiter` (token-bucket con `anyio.sleep`). En producción
el rate limit se puede ajustar vía `Source.rate_limit_rps`.

### Caching y reproducibilidad

- Descarga raw: `data/raw/<source>/<source_id>.<ext>` (checksum sha256)
- Documento canónico: `data/canonical/<source>/<source_id>.json`
- `IngestStorage` es idempotente: si `checksum` coincide → skip sin re-descarga
- El directorio `data/` está en `.gitignore`; sólo los ficheros de fixtures
  en `tests/fixtures/` se commitean

### Tests: siempre con fixtures locales en CI

Los tests unitarios **nunca** hacen solicitudes HTTP reales. Cada fuente tiene
fixtures XML precomittadas en `packages/ingest/tests/fixtures/<source>/`.
Las pruebas usan `respx` para mockear `httpx.AsyncClient`.

Para capturar una fixture nueva:

```bash
python scripts/capture_fixture.py boe BOE-A-2014-6732
python scripts/capture_fixture.py eurlex 32013R0575
```

## Consequences

- **Bueno**: APIs oficiales son estables y respetan robots.txt / ToS
- **Bueno**: fixtures deterministas → CI reproducible sin acceso a red
- **Bueno**: checksum idempotente evita re-indexación innecesaria
- **Limitación**: si la API oficial no está disponible para un documento
  histórico, hay que añadir lógica ad-hoc en la fuente correspondiente
- **Limitación**: Fase 2 no soporta PDF de EUR-Lex; se añade en Fase 3/4

## Añadir una fuente nueva

Ver `docs/ingest.md` — sección "Añadir una fuente nueva".
