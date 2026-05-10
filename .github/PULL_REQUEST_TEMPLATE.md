## Summary

<!-- What does this PR do and why? 2-3 sentences. -->

## Type of change

- [ ] feat — new feature
- [ ] fix — bug fix
- [ ] refactor — no behaviour change
- [ ] docs / ADR
- [ ] chore — deps, tooling, config
- [ ] ci — GitHub Actions, pre-commit
- [ ] perf

## Checklist

- [ ] Tests added or updated (unit + integration where applicable)
- [ ] Affected evals run green (`make eval-quick`)
- [ ] Docs / ADRs updated (if architecture or decision changed)
- [ ] Prompts versioned (`docs/prompts/<agent>/v<N>.md`) if prompt changed
- [ ] No secrets committed (gitleaks and detect-secrets pass)
- [ ] PII redacted in logs (no raw query strings at INFO level)
- [ ] `mypy --strict` passes (`make type-check`)
- [ ] `ruff` lint passes (`make lint`)
- [ ] PR title follows Conventional Commits format

## Legal / compliance notes

<!-- If this PR touches agent output, citation logic, or verification:
     describe the expected impact on citation recall / hallucination rate. -->

## Screenshots / recordings

<!-- For frontend changes only. -->
