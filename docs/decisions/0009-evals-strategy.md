# ADR 0009 — Evaluation Strategy

**Status:** Accepted  
**Date:** 2026-05-11  
**Deciders:** ibernale

---

## Context

lex-agents generates legal advice backed by citations. We need a way to
measure quality objectively, prevent regressions in CI, and give the team
a signal when model updates or prompt changes degrade legal accuracy.

The system produces structured outputs (citations, verification reports,
routing decisions) that make deterministic evaluation feasible without
requiring LLM-as-judge.

---

## Decision

### Two-tier CI evaluation

**Smoke** (5 cases, ~30 s) runs on every push to `main` that touches core
packages or prompts. **Full** (30 cases) runs nightly and on
`workflow_dispatch`. Both compare against a stored baseline artifact.

### Why not LLM-as-judge

| Concern | Detail |
|---------|--------|
| **Determinism** | LLM judges produce different scores on re-runs; flaky CI is unusable |
| **Cost** | Evaluating 30 legal responses with a capable judge model costs ~$5–10/run; at nightly cadence this compounds |
| **Latency** | Adding a judge pass doubles wall-clock time for smoke runs |
| **Circularity** | Using the same provider's model to judge its own outputs introduces correlated errors |

The structured verification report already captures citation correctness;
text matching on `must_mention_concepts` and `must_not_claim` is sufficient
for the MVP.

### Why expert_reviewed=false in MVP

Generating a gold-standard legal dataset requires qualified jurists to
review every case — a process that takes weeks and significant legal
expertise. For the MVP we prioritise having *some* automated quality signal
over having *no* signal. All 30 cases carry a prominent `expert_reviewed:
false` flag and a `notes` field explaining the limitation.

The path to `expert_reviewed: true`:
1. A qualified banking-law jurist reviews the case in a PR.
2. They sign off with their name and professional capacity.
3. The YAML is updated and the PR is approved by a team lead.
This process is a prerequisite for any production or corporate deployment.

### Thresholds

| Metric | Smoke | Full | Rationale |
|--------|-------|------|-----------|
| `forbidden_claim_rate` | > 0 | > 0 | Any hallucinated normative statement is a hard stop |
| `citation_recall` | < 0.70 | < 0.70 | Below 70% means the system regularly omits required sources |
| `hallucination_rate` | > 0.10 | > 0.10 | > 10% broken/uncited evidence is legally unacceptable |
| `legal_quality_score` | < baseline × 0.95 | < baseline × 0.95 | 5% regression triggers review |
| `latency_p95` | — | > 30 000 ms | SLA for internal tooling |
| `cost_per_query` | — | > $0.50 | Cost control |

### Metric weights

Weights in `evals/config/weights.yaml` reflect that citation quality
(recall + precision = 60%) matters most for a legal advice system.
`hallucination_free` (20%) penalises broken references severely.
Concept and caveat coverage (15% total) ensure completeness.

---

## Consequences

**Positive:**
- Automated regression detection on every main push
- Transparent, reproducible metrics (no LLM non-determinism)
- Incremental path to expert-validated ground truth

**Negative:**
- Text-matching metrics can miss paraphrased correct answers (low false-negative risk for legal text, which is precise by nature)
- `expert_reviewed=false` limits the legal defensibility of the benchmark until reviewed
- Maintaining 30+ YAML cases requires discipline as regulation evolves

---

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| LLM-as-judge | Non-deterministic, costly, circular (see above) |
| RAGAS framework | Requires embedding model at eval time; adds infra complexity; less control over legal-specific metrics |
| Manual QA only | Doesn't scale, can't block CI |
| A/B production shadow | Requires production traffic; not available at MVP stage |
