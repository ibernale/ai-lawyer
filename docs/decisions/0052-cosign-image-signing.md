# 0052 — Cosign Keyless Image Signing for ECR

**Status:** Accepted
**Date:** 2026-05-14

## Context

DORA Article 9.4 requires financial institutions to implement controls ensuring
the integrity of software and systems used for ICT services. In practice this
means verifying that container images deployed to production have not been
tampered with between build and deployment — a supply chain integrity control.

lex-agents builds Docker images in GitHub Actions and pushes them to Amazon ECR.
Without image signing, an attacker who gains write access to ECR (via leaked
credentials or misconfigured IAM) could replace a production image with a
malicious one, and ECS would pull and run it silently.

Two options were considered:
1. **Cosign with a KMS-managed key** — requires creating a KMS asymmetric key,
   managing key access policies, and rotating the key.
2. **Cosign keyless (Sigstore OIDC)** — uses GitHub Actions OIDC token to
   produce a short-lived signing certificate anchored to Sigstore's Rekor
   transparency log. No long-lived private key to manage or leak.

We already use GitHub Actions OIDC for ECR authentication (ADR 0046) and AWS
credential federation (ADR 0044). Extending the same OIDC token to cosign
keyless signing introduces no new secret management.

## Decision

Use **cosign keyless signing** (Sigstore OIDC via GitHub Actions) for all
Docker images pushed to ECR.

The `app-deploy.yml` workflow adds a `cosign sign` step immediately after
`docker push`. The signature is anchored to the GitHub Actions workflow identity
(`repo:ibernale/ai-lawyer:ref:refs/heads/main`) and recorded in Sigstore's
Rekor public transparency log.

ECS task definitions reference image digests (`@sha256:...`) rather than
mutable tags so that signed images cannot be silently swapped.

Verification is available via:
```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/ibernale/ai-lawyer" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  $ECR_REGISTRY/$ECR_REPO:$TAG
```

## Consequences

**Positive:**
- No KMS key to manage, rotate, or protect.
- Signing identity is cryptographically bound to the GitHub Actions workflow;
  even an AWS admin cannot produce a valid signature without GitHub access.
- Signatures are publicly auditable via Rekor transparency log.
- Addresses DORA Art. 9.4 supply chain integrity requirement.
- Zero cost (Sigstore is free and open-source).

**Negative:**
- Requires internet access from the GitHub Actions runner to Sigstore endpoints
  (`fulcio.sigstore.dev`, `rekor.sigstore.dev`). These are public infrastructure
  with high availability but no SLA from Sigstore.
- Verification requires cosign installed on the verifying machine.
- If Sigstore is unreachable, the `cosign sign` step fails and deployment is
  blocked. Mitigation: add `continue-on-error: false` so failures are explicit,
  not silent.
- Signatures are tied to the GitHub OIDC issuer. If the repo is moved or renamed,
  existing signatures remain valid but new ones will have a different identity.

**Operational impact:**
- `app-deploy.yml` gains one step (~10s overhead).
- `infra/cdk/lib/stacks/app-services.ts` should reference image digests in ECS
  task definitions for full integrity guarantee (planned in Fase 10, not Fase 9.5).

## Alternatives considered

**Cosign with KMS key:**
- Pro: works in air-gapped environments.
- Con: requires managing an asymmetric KMS key (cost, policy, rotation).
- Rejected: unnecessary complexity for our threat model.

**Docker Content Trust (Notary v1):**
- Pro: native Docker ecosystem.
- Con: Notary v1 is deprecated upstream; AWS ECR support is limited.
- Rejected.

**No signing:**
- Rejected: fails DORA Art. 9.4 supply chain integrity requirement.
