---
id: "0022"
title: "Memory Implementation — Procedural + Semantic Layers"
status: accepted
date: "2026-05-11"
authors: ["ibernale"]
relates_to: ["0013", "0012", "0015"]
---

## Context

ADR 0013 established the policy for stratified memory (procedural, semantic, episodic) with human-only write governance. This ADR records the concrete implementation decisions for the procedural and semantic layers deployed in Fase 6.4. Episodic memory remains disabled per ADR 0013 §3 (RGPD risk, self-modification loop, consistency).

## Decision

### Procedural memory — SQLite (read-only at runtime)

**Schema** (`packages/memory/seed/procedural_patterns_seed.sql`):

```sql
CREATE TABLE IF NOT EXISTS procedural_patterns (
    id          INTEGER PRIMARY KEY,
    pattern_key TEXT NOT NULL UNIQUE,
    version     INTEGER NOT NULL DEFAULT 1,
    content     TEXT NOT NULL,   -- JSON: {applies_when, instructions}
    source      TEXT NOT NULL,   -- "human:seed" | "human:pr#N"
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);
```

**Invariant**: No INSERT, UPDATE, or DELETE is permitted from runtime agent code. `ProceduralStore` exposes only `init_db()` and `get_active_patterns()`. Write access is exclusively via `make procedural-edit` → edit `procedural_patterns_seed.sql` → PR reviewed by @ibernale → merged to main.

**Matching logic**: Each pattern's `content` JSON contains an `applies_when` dict with `keywords` (list[str]) and/or `output_types` (list[str]). A pattern fires if at least one keyword appears in the query (case-insensitive) OR the requested `output_type` is in `output_types`. Patterns with empty `applies_when` always fire.

**Seed patterns** (v1.0, 7 patterns):
- `output_template:dictamen` — mandatory 5-section structure
- `output_template:memo_comite` — executive 1-page format
- `routing:crr_transitional_caveat` — fires on CRR III / transitorio / Basilea IV
- `routing:cross_jurisdiction_note` — fires on cross-border / filial / internacional
- `citation:reglamento_ue_format` — CELEX citation format for EU regulations
- `citation:circular_bde_format` — citation format for BdE circulars
- `quality:mifid_applicability_check` — fires on MiFID / instrumento financiero

### Semantic memory — YAML files (version-controlled)

**Location**: `docs/knowledge/` — four files with mandatory header (`_schema_version`, `_description`, `_last_updated`, `_edit_policy: "PR-only, reviewed by @ibernale"`).

**Files**:
- `jurisdictions.yaml` — 11 jurisdictions with supervisor, currency, regime
- `internal-glossary.yaml` — 15 internal terms (abbreviations + descriptions)
- `regulatory-frameworks.yaml` — 16 frameworks with CELEX/BOE references
- `output-templates.yaml` — 4 output types with structure + mandatory caveats

**Validation**: `make validate-knowledge` invokes `lex_agents_memory.semantic.validator.validate_all()` — checks header keys + section-specific required fields. Called by CI (`adversarial.yml`) and by `SemanticLoader.__init__()` at startup (warning-only, never blocks runtime).

**JSON schemas**: `docs/knowledge/schemas/` — four draft-07 schemas for tooling and documentation; not enforced at runtime (validator.py is authoritative).

### Integration point — LegalPlanner

`LegalPlanner.__init__` accepts `memory_injector: MemoryInjector | None = None`. If present, `plan()` calls `memory_injector.build_context(query, jurisdictions, output_type)` **before** the API call. A non-empty result is prepended to `user_msg` with `"\n\n---\n\n"` separator. Span attributes logged: `memory.injected` (bool), `memory.context_len` (int).

**Budget cap**: `SemanticInjector` truncates context at `_BUDGET_CHARS = 8000` chars (~2000 tokens) to avoid overloading the Planner prompt.

**Backwards compatibility**: `memory_injector=None` (default) leaves `plan()` behavior identical to pre-Fase-6.4.

### Graceful degradation

| Failure mode | Behaviour |
|---|---|
| `knowledge_dir` does not exist | `SemanticLoader` logs warning, returns `{}`, `SemanticInjector` returns `""` |
| YAML validation errors | `SemanticLoader` logs warnings, continues loading valid files |
| DB file does not exist | `ProceduralStore` logs warning, returns `[]` |
| `seed_sql_path` not set | `ProceduralLoader` returns `[]` |
| `MemoryInjector.build_context()` returns `""` | Planner skips injection, operates normally |

## Consequences

- Agent memory is fully auditable: every pattern has a `source` field tracing it to a human PR.
- No agent self-modification is possible at runtime (enforced by API surface, not just policy).
- Adding or modifying patterns requires a PR — which enforces review and creates an audit trail.
- Semantic knowledge is updated by editing YAML files (PR-only), not through any agent write path.
- If `MemoryInjector` raises unexpectedly (e.g., DB corruption), it propagates to the caller — callers should wrap in try/except if they need complete isolation. This is intentional: silent failures would hide configuration drift.
