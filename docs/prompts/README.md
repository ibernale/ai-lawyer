# Versioned Prompts

All prompts follow a strict versioning scheme to ensure reproducibility and auditability of legal AI outputs.

## Directory structure

```
docs/prompts/
├── router/
│   ├── v1.md
│   └── tests/v1.yaml
├── especialistas/
│   └── regulatorio_bancario_ue_es/
│       ├── v1.md
│       └── tests/v1.yaml
├── sintesis/
│   └── v1.md
├── verificador/
│   ├── v1.md
│   └── tests/v1.yaml
└── README.md
```

## Frontmatter schema

Every prompt file begins with YAML frontmatter:

```yaml
---
name: <path/to/prompt>       # matches directory path
version: <int>               # increment on breaking changes
model: <model-id>            # exact Anthropic model ID
temperature: <float>         # 0.0–1.0
max_tokens: <int>
owner: <team-or-person>
last_review_date: <YYYY-MM-DD>
change_summary: <one-line description>
---
```

## When to create a new version

Create `v(N+1).md` when:
- The model ID changes
- Temperature or max_tokens change significantly
- The prompt structure changes (new/removed sections)
- Output format or tool schema changes

**Do NOT create a new version for:** typo fixes, minor wording clarifications that don't change semantics.

## Loading prompts in code

```python
from lex_agents_agents.prompt_loader import load_prompt

cfg = load_prompt("router", version=1)
# cfg.model, cfg.temperature, cfg.max_tokens, cfg.body, cfg.content_hash
```

The loader caches by `(name, version)` — subsequent calls return the same object with no I/O. The `content_hash` (sha256 of body) is logged in every agent call for auditability.

## Running prompt tests

Prompt test YAMLs are reference cases for manual review and future eval harness integration. They document expected routing decisions and output structure — not executed by pytest directly.
