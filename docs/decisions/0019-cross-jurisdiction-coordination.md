# ADR 0019 — Cross-Jurisdiction Coordination Strategy

**Date**: 2026-05-11  
**Status**: Accepted  
**Deciders**: lex-agents team

---

## Context

Legal queries in the banking domain regularly span multiple legal orders simultaneously: a syndicated loan to a UK counterparty involves CRR prudential rules (EU), EBA guidelines (EU), post-Brexit equivalence (UK), and potentially RGPD if personal data is involved. Prior to Fase 6.2, the system routed every query to exactly one specialist branch, losing cross-branch insights.

---

## Decision

### Parallel Makers pattern

When the Planner detects multiple relevant branches, `CrossJurisdictionCoordinator.run_parallel()` executes all Maker specialists concurrently via `asyncio.gather(..., return_exceptions=True)`. Each branch task carries its own query (Planner rewrites the user query per branch) and a weight (0–1, sum≈1).

`return_exceptions=True` ensures that a single branch failure does not discard all other successfully-computed responses. Failed branches are logged and excluded; if all branches fail the coordinator raises `RuntimeError` to propagate the failure cleanly.

### EU > national hierarchy

The synthesis prompt (`docs/prompts/sintesis/v2.md`) instructs the LLM to:

1. Prefer EU-law positions when EU and national law address the same aspect — mark with `[EU-PREF]`
2. Flag genuine contradictions inline as `⚠️ DISCREPANCIA NORMATIVA` rather than silently picking one position
3. Weight branch contributions by the `weight` field from the Planner output

The hierarchy is enforced at synthesis time, not at routing time. This is intentional: the specialist runs with full autonomy over its domain, and the synthesizer applies the hierarchy after seeing all branch outputs.

### Synthesis fallback

If the LLM synthesis call fails (API error, timeout), the coordinator falls back to `_fallback_merge()`: branch outputs are concatenated with `## Análisis: <branch>` headers and `---` separators. The output is structurally weaker but preserves all legal analysis. The user always receives some answer; the disclaimer banner covers validation requirements.

### Citation merging

Citations from all branches are merged into a single sequential list. Deduplication is by `(source_id, chunk_id)` key — the same regulatory chunk referenced by two branches appears once. Indices are renumbered sequentially (1, 2, 3, …) across the merged list.

### Depth integration

| depth    | Coordination                                                                 |
| -------- | ---------------------------------------------------------------------------- |
| shallow  | Single specialist, no coordination                                           |
| standard | Planner → parallel Makers if >1 branch → LLM synthesis                       |
| deep     | Planner → parallel Makers → Judge → (revise → repeat Makers) → LLM synthesis |

The Judge evaluates the synthesized output against the Planner's `DefinitionOfDone`. The DoD carries `must_consider_jurisdictions` from the Planner, ensuring the Judge flags responses that miss a required jurisdiction.

### Iteration cap

The Judge loop runs at most 2 iterations (`_MAX_ITERATIONS = 2`). At iteration 2 a `revise` verdict is overridden to `publish` with `[verification_partial=True]` in the iteration brief. This prevents infinite loops in adversarial or low-quality LLM scenarios. See ADR 0014 for the LeMaJ (LLM-as-Judge) general policy.

---

## Consequences

**Positive**:

- Multi-branch queries receive integrated analysis rather than a single-branch approximation
- EU > national hierarchy is explicit and auditable from the synthesis prompt
- Contradictions are surfaced to the reader rather than silently resolved
- Branch failures are isolated; one failing specialist does not kill the entire consult

**Negative**:

- Synthesis adds one LLM call (claude-opus-4-7) per multi-branch query — approximately $0.01–0.05 extra cost depending on branch count and response length
- Branch/response alignment in `synthesize()` assumes `run_parallel()` returns responses in the same order as `sub_tasks` sorted by priority; this invariant must be preserved if `run_parallel()` is modified
- Cross-jurisdiction integration is tested at the unit level with mocked specialists; end-to-end quality requires human expert review (eval stub CROSS-004, `run_in: fase_6_3`)

---

## Alternatives considered

**Sequential chaining (branch 1 output → branch 2 input)**: rejected — creates ordering bias and doubles latency unnecessarily.

**Single specialist with cross-branch system prompt**: rejected — a single specialist prompt cannot maintain depth across all six legal domains simultaneously; specialist quality degrades.

**Static merge without LLM synthesis**: viable fallback (implemented as `_fallback_merge`), but does not apply EU>national hierarchy or resolve contradictions.
