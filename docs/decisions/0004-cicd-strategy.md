# 0004 — Estrategia CI/CD

**Status:** Accepted
**Date:** 2026-05-10

## Context

lex-agents handles sensitive legal content for a banking institution. The CI/CD
pipeline must guarantee that no code reaches production without passing quality
gates, security scans, and type checks. At the same time, it must be fast enough
to not impede daily development velocity.

## Decision

### GitHub Actions (not Jenkins or CircleCI)

GitHub Actions is co-located with the source repository — no extra service to
operate. It has native integration with GHCR (container registry), CodeQL
(SAST), Dependabot, and branch protection rules. For an internal tool with a
small team, the operational overhead of a separate CI server is not justified.

### Pipeline structure

Four workflows, each with a clear and non-overlapping responsibility:

| Workflow       | Trigger             | Purpose                                                      |
| -------------- | ------------------- | ------------------------------------------------------------ |
| `ci.yml`       | push + PR to main   | Fast feedback: lint, types, tests, secrets scan, image build |
| `security.yml` | weekly + on-demand  | Deep scan: CodeQL, pip-audit, npm audit, Trivy               |
| `evals.yml`    | nightly + on-demand | Legal quality regression (Fase 4)                            |
| `release.yml`  | tag `v*`            | Build, sign, push release images; generate changelog         |

`ci.yml` jobs run in parallel. `build-images` gates on all other jobs passing.
Image push to GHCR only on merge to `main` (not on PRs) to avoid polluting the
registry with unreviewed code.

### Branch protection (applied manually in GitHub Settings)

Required settings for `main`:

- Require a pull request before merging (no direct pushes)
- Require status checks to pass: `lint-py`, `typecheck-py`, `test-py`,
  `lint-web`, `typecheck-web`, `test-web`, `secrets-scan`
- Require at least 1 approving review
- Dismiss stale reviews when new commits are pushed
- Do not allow force pushes
- Do not allow branch deletion

See `docs/runbook.md` for the exact GitHub UI steps.

### GHCR as container registry

GitHub Container Registry (`ghcr.io/ibernale/ai-lawyer/...`) is chosen because:

1. Zero additional authentication — same GitHub token used by Actions
2. Co-location with source and CI — no cross-service latency
3. Package visibility inherits repo visibility (private by default)
4. Free for public repos; acceptable cost for private

### Image signing with cosign (keyless)

Images built on release tags are signed using Sigstore cosign keyless signing
(OIDC-based, no long-lived key material). This is set to `continue-on-error`
until Fase 5 enforces signature verification in deployment.

### Caching strategy

- Python: uv cache keyed on `hashFiles('**/pyproject.toml')`, stored via
  `actions/cache@v4`
- Node: pnpm built-in cache via `setup-node` `cache: "pnpm"`
- Docker: BuildKit GHA cache (`type=gha, mode=max`) for layer reuse across PRs

## Consequences

- All merges to `main` require a PR — no direct pushes.
- A failing `secrets-scan` job blocks the entire pipeline.
- Image tags follow `ghcr.io/ibernale/ai-lawyer/<service>:<git-sha>` for
  traceability and `:<version>` for releases.

## Alternatives considered

| Alternative          | Rejected because                                                |
| -------------------- | --------------------------------------------------------------- |
| Jenkins              | Requires dedicated server ops; no native GitHub integration     |
| CircleCI             | Additional service to manage; cost vs. GitHub Actions free tier |
| ECR / DockerHub      | Extra authentication; no native GitHub token integration        |
| Separate signing key | Key rotation burden; keyless is simpler and equally secure      |
