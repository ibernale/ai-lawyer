---
name: legal-source-ingestion
description: |
  Use this skill when implementing, extending, or repairing scrapers for legal
  sources (BOE, EUR-Lex, future CENDOJ). Covers the Source interface contract,
  rate limiting rules, storage conventions, test fixture approach, and
  documentation requirements for new sources.
---

## Source interface

Every source adapter must implement:

```python
from abc import ABC, abstractmethod
from shared.types import CanonicalDocument, RawDocument

class Source(ABC):
    source_id: str           # e.g. "BOE", "EURLEX"
    base_url: str
    rate_limit_rps: float    # default 1.0

    @abstractmethod
    async def list_documents(
        self,
        from_date: date,
        to_date: date,
        doc_types: list[str] | None = None,
    ) -> list[str]:
        """Return document IDs available in the date range."""

    @abstractmethod
    async def fetch(self, doc_id: str) -> RawDocument:
        """Download and return raw document (HTML/XML + metadata)."""

    @abstractmethod
    def parse_to_canonical(self, raw: RawDocument) -> CanonicalDocument:
        """Parse raw to canonical structure with hierarchy + chunks."""
```

`CanonicalDocument` includes: `source_id`, `document_type`, `eli_uri`,
`full_text`, `chunks: list[Chunk]`, `checksum`.

## Ethical scraping rules

1. **Always check `robots.txt`** before first request. Fail loudly if
   path is disallowed.
2. **Rate limit**: ≤ 1 req/s default. Configurable per source via
   `INGEST_RATE_LIMIT_<SOURCE>` env var. Never exceed stated limit.
3. **User-Agent**: `lex-agents/0.x (+internal; contact: <CONTACT_EMAIL>)`
4. **Prefer official APIs**: EUR-Lex SPARQL + REST API > HTML scraping.
   BOE uses its official XML API (`https://boe.es/diario_boe/xml.php`).
5. **Exponential backoff** on 429 / 503 (tenacity, max 5 retries).

## Storage layout

```
data/
  raw/<source>/<YYYY>/<doc_id>.<ext>       # original download, never modified
  canonical/<source>/<YYYY>/<doc_id>.json  # parsed CanonicalDocument
```

Both directories are gitignored. `checksum` in canonical = sha256 of raw file.
If raw file already exists with same checksum → skip download (idempotent).

## Tests — fixture-based only

- Record real HTTP responses as fixtures: `tests/fixtures/<source>/<doc_id>.<ext>`
- Tests use `respx` (httpx mock) or `responses` to replay fixtures
- **Never hit live sources in CI**
- Fixture filenames: `<doc_id>_<YYYY-MM-DD>.xml` (date = capture date)
- Document fixture capture in `scripts/capture_fixture.py` (one-time manual run)

## Dagster asset pattern (Fase 6.1+)

Sources no longer run as CLI scripts — they are invoked by the Dagster pipeline
in `packages/pipeline/`. Each source corresponds to an asset group `<source_id>`
that runs `raw → canonical → chunked → contextualized → embedded → indexed`.

**Re-materialization is automatic via `DataVersion`:**
- `*_chunked` version = hash of `LegalChunker` config
- `*_contextualized` version = sha256 of active prompt file
- `*_embedded` version = embedder model name

Changing any of these causes Dagster to mark downstream assets as *stale*.
`reindex_all_job` re-embeds and re-indexes without re-downloading.

**To add a new source to the Dagster pipeline:**
1. Implement the `Source` in `packages/ingest/sources/<source_id>.py`
2. Add lazy import in `packages/pipeline/src/lex_agents_pipeline/assets/raw.py`
3. Add `_make_raw_asset(...)` call for the new source in `raw.py`
4. Add corresponding canonical/chunked/contextualized/embedded/indexed calls
5. Add job in `jobs/ingest_jobs.py`
6. Add schedule in `schedules/cron.py`
7. Set correct `domain=` in `_SOURCE_DOMAIN` dict in `indexed.py` (ADR 0010)
8. Add `docs/sources/<source_id>.md`

**Asset checks required for every source group:**
- `raw`: `n_docs >= 1`, no zero-byte files
- `canonical`: `parse_error_rate < 5%`
- `indexed`: collection exists, `points_count > 0`

## New source checklist

1. Create `packages/ingest/sources/<source_name>.py` implementing `Source`
2. Add fixtures to `tests/fixtures/<source_name>/`
3. Write unit tests covering: `list_documents`, `fetch` (mocked), `parse_to_canonical`
4. Document in `docs/sources/<source_name>.md`:
   - API / URL structure
   - Rate limits and ToS reference
   - Términos de uso (with date of consultation)
   - User-Agent used: `lex-agents/0.1 (+https://github.com/ibernale/ai-lawyer)`
   - Document types covered
   - Known edge cases (e.g. corrigendums, consolidated texts)
   - How format changes are detected (what makes the parser fail)
5. Wire into Dagster pipeline (see "Dagster asset pattern" above)
6. Add ADR if this source introduces a new data format or parsing strategy

## EUR-Lex specifics

- Use CELLAR SPARQL endpoint for metadata enumeration
- Use REST API for full-text XML (`https://publications.europa.eu/resource/cellar/<id>`)
- CELEX number is the canonical `source_id`

## BOE specifics

- Use XML API: `GET https://boe.es/diario_boe/xml.php?id=<doc_id>`
- Document IDs follow pattern `BOE-A-YYYY-NNNNN`
- Consolidated texts available via `CELEX`-equivalent ELI URI
