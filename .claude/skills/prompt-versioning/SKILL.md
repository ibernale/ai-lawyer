---
name: prompt-versioning
description: |
  Use this skill when creating, editing, or reviewing system prompts for any
  lex-agents agent (router, specialist, synthesizer, verifier). Enforces the
  versioning path convention, frontmatter schema, test file format, and the
  rule that any structural change requires a new version number and optionally
  an ADR.
---

## Directory layout

```
docs/prompts/
  <agent-name>/
    v1.md
    v2.md
    tests/
      01_basic_query.yaml
      02_multi_article.yaml
```

Agent names: `router`, `regulatorio_bancario_ue_es`, `synthesizer`, `verifier`.

## Prompt file frontmatter (required)

```yaml
---
name: regulatorio_bancario_ue_es
version: 3
model: claude-opus-4-7
temperature: 0.1
max_tokens: 4096
owner: "@legal-team"
last_review_date: 2025-10-01
change_summary: |
  Added explicit instruction to declare missing citations rather than
  omit the claim. Fixes hallucination pattern observed in eval set v2.
---
```

All fields are mandatory. `temperature` must be ≤ 0.3 for specialist agents.

## Version increment rules

| Change | Version bump |
|--------|-------------|
| Typo fix, whitespace | Same version, update `last_review_date` |
| Instruction wording | Patch (v1 → v1.1 or next integer) |
| New section / structural change | New integer version + consider ADR |
| Model or temperature change | New integer version + ADR required |

Use integer versions (v1, v2, v3). Do not use semver for prompts.

## Test file format

```yaml
# docs/prompts/<agent>/tests/<n>_<description>.yaml
description: "Query with two conflicting articles"
input:
  query: "¿Cuál es el requisito de capital mínimo bajo CRR2?"
  retrieved_chunks:
    - chunk_id: "boe-2019-123-art42"
      text: "..."
expected:
  properties:
    - has_citation: true
    - no_hallucination: true
    - status_marker_present: true
    - caveat_present: true
  forbidden:
    - pattern: "vigente sin cita"
```

Tests check *properties*, not exact string matches. Run with `make eval-quick`.

## Loading prompts in code

```python
from shared.prompt_loader import load_prompt

prompt = load_prompt("regulatorio_bancario_ue_es", version=3)
# Logs: {"prompt_name": "...", "prompt_version": 3, "model": "..."}
```

Never hardcode prompt text in Python or TypeScript source files.
Prompt version used must appear in the response JSON (`meta.prompt_version`).

## ADR requirement

Open an ADR in `docs/decisions/` whenever:
- Model changes
- Temperature changes by more than 0.1
- A new mandatory output section is added
- A section is removed or renamed
