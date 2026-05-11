# Eval Framework

Reproducible evaluation suite for lex-agents. Measures legal quality on every
release; blocks CI regressions.

## Quick start

```bash
# ~30 seconds — 5 smoke cases, no real Qdrant needed for dry runs
make eval-quick

# Full suite — 30 cases, requires running services
make eval
```

Results land in `evals/reports/<timestamp>/`:

| File            | Contents                           |
| --------------- | ---------------------------------- |
| `results.jsonl` | One JSON per case (CaseResult)     |
| `metrics.json`  | Aggregated RunSummary (read by CI) |
| `summary.md`    | Human-readable markdown table      |
| `manifest.json` | git SHA, models, dataset SHA       |

## Metrics

| Metric                 | Definition                              | Weight |
| ---------------------- | --------------------------------------- | ------ |
| `citation_recall`      | Fraction of expected citations found    | 0.35   |
| `citation_precision`   | `claims_passed / claims_total`          | 0.25   |
| `hallucination_free`   | `1 - hallucination_rate`                | 0.20   |
| `concept_coverage`     | Fraction of required concepts in answer | 0.10   |
| `forbidden_claim_free` | `1 - forbidden_claim_rate`              | 0.05   |
| `caveat_coverage`      | Fraction of expected caveats mentioned  | 0.05   |

`legal_quality_score` = weighted average. Range [0, 1]; higher is better.

`hallucination_rate` = `(broken_refs + uncited_claims) / (claims_total + 1)`

## CI thresholds (smoke job)

| Metric                 | Threshold         | Action                   |
| ---------------------- | ----------------- | ------------------------ |
| `forbidden_claim_rate` | > 0               | Hard fail                |
| `citation_recall`      | < 0.70            | Hard fail                |
| `hallucination_rate`   | > 0.10            | Hard fail                |
| `legal_quality_score`  | < baseline × 0.95 | Hard fail (compare step) |

Full job adds: `latency_p95 > 30 000 ms`, `cost_per_query > $0.50`.

## Dataset schema

```yaml
id: BANK-EU-001
jurisdiction: [ES, EU]
branch: regulatorio_bancario_ue_es
difficulty: easy # easy | medium | hard
expert_reviewed: false # always false until signed by a qualified jurist
query: "¿Cuáles son los requisitos de capital CET1?"
expected:
  must_cite_any_of:
    - { type: regulation, celex: "32013R0575", articles: ["92"] }
  must_mention_concepts: ["capital ordinario de nivel 1", "ratio CET1"]
  must_not_claim: ["Basilea IV está plenamente en vigor en la UE"]
  expected_caveats: ["sujeto a modificaciones por CRR3"]
  output_type: dictamen
notes: "..."
```

For out-of-scope cases: `branch: fuera_de_alcance`, empty `must_cite_any_of`.

## Adding a case

1. Copy `evals/golden_dataset/BANK-EU-001.yaml` as a template.
2. Pick the next sequential ID.
3. Fill `query`, `expected.*`, `notes`.
4. Keep `expert_reviewed: false` until a qualified jurist reviews and signs in a PR.
5. To promote to smoke set: copy to `evals/golden_dataset_smoke/`.

## Running with filters

```bash
# Only hard cases
uv run python -m evals run --dataset evals/golden_dataset --filter difficulty=hard

# Compare two runs
uv run python -m evals compare \
  --baseline evals/reports/20260101T120000/ \
  --candidate evals/reports/20260201T120000/
```

## Overriding a regression

If CI fails due to a metric regression that is intentional (e.g. a model
downgrade for cost reasons), follow this process:

1. Provide a justification comment in the PR describing why the regression
   is acceptable.
2. Get approval from at least one senior team member.
3. Update the baseline artifact in GitHub Actions by running
   `workflow_dispatch` with mode=full on main after merge.

Do **not** silence the threshold check in code — use the approval process.

## Promoting expert_reviewed to true

`expert_reviewed: false` is the default for all auto-generated cases. To
upgrade a case:

1. A qualified banking-law jurist must review the `query`, all
   `must_cite_any_of` items, `must_mention_concepts`, and `must_not_claim`.
2. They sign off in a PR with their name and professional capacity.
3. Set `expert_reviewed: true` in the YAML.
4. This is a **prerequisite** for any production or corporate deployment.

## Exploring results

Open `evals/notebooks/explore_results.ipynb` to load all historical runs
and visualise the heatmap (difficulty × metric) and the temporal evolution
of `legal_quality_score`.
