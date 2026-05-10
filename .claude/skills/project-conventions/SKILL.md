---
name: project-conventions
description: |
  Use this skill when you need to follow or enforce the contribution conventions
  for lex-agents: commit messages, branching strategy, PR process, language
  rules, versioning, and ADR creation.
---

## Commit messages — Conventional Commits

Format: `<type>(<scope>): <description>`

| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code restructure, no behaviour change |
| `test` | Test additions or corrections |
| `chore` | Build, tooling, deps |
| `ci` | GitHub Actions, pre-commit |
| `perf` | Performance improvement |

Scope is the package name: `api`, `agents`, `rag`, `verifier`, `ingest`,
`shared`, `web`, `infra`, `evals`, or omitted for cross-cutting changes.

Examples:
```
feat(agents): add regulatorio_bancario_ue_es specialist
fix(verifier): handle empty chunk list without crashing
docs(rag): document hybrid search configuration
chore(deps): bump anthropic to 0.35.0
```

Breaking changes: append `!` after scope and add `BREAKING CHANGE:` footer.

## Branching — trunk-based

- `main` — production-ready, protected, requires PR + review
- `feat/<short-description>` — feature branches
- `fix/<short-description>` — bug fix branches
- `chore/<short-description>` — tooling, deps, config
- `ci/<short-description>` — CI changes

Branch off `main`, rebase before PR, squash-merge preferred.

## Pull requests

Always use `.github/PULL_REQUEST_TEMPLATE.md`. All checklist items must be
ticked before merge. Assign CODEOWNERS automatically.

## Language rules

- **Code, identifiers, comments, commit messages, ADRs, PR descriptions** → English
- **Legal docs, system prompts for legal specialists, runbook** → Spanish
- Mix is intentional: code stays parseable by any engineer; legal content
  stays natural for Spanish-speaking lawyers.

## Versioning

SemVer per package (`packages/*/pyproject.toml`). Bump on every release tag.
API: `v0.x` during MVP, `v1.0` when first external tenant onboards.

## ADRs

Path: `docs/decisions/NNNN-kebab-title.md`
Number sequentially. Template:

```markdown
# NNNN — Title

**Status:** Proposed | Accepted | Deprecated | Superseded by NNNN
**Date:** YYYY-MM-DD

## Context
## Decision
## Consequences
## Alternatives considered
```

Create ADR when: changing stack component, adding external dependency,
changing prompt structure, changing citation format, changing eval schema.
