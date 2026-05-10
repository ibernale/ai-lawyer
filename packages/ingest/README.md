# packages/ingest

Legal source scrapers and ingestion pipeline for lex-agents. Implements the
`Source` interface for BOE (Boletín Oficial del Estado) and EUR-Lex, with
methods `list_documents`, `fetch`, and `parse_to_canonical`. Stores raw,
canonical, and checksummed artifacts. Respects robots.txt, applies rate
limiting (≤ 1 req/s default), and uses official APIs where available over
HTML scraping. See `docs/sources/` for per-source documentation.
