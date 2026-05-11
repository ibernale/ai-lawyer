# ADR 0008 — Citation Verifier Architecture

**Status:** Accepted
**Date:** 2026-05-11
**Deciders:** lex-agents team

## Context

Legal AI systems exhibit high hallucination rates for citations. Dahl et al. (2024) found that
GPT-4 fabricated legal citations in 75%+ of responses when used without RAG. Even with RAG,
models may misattribute or misquote source material.

The lex-agents platform indexes source chunks and assembles context with `[REF:n]` markers. We
need to verify that each normative claim in the generated response is actually supported by the
cited chunk, before the response is returned to the user.

Requirements:

- Deterministic where possible (auditable, reproducible)
- Low latency overhead (most responses should not need LLM calls)
- Clear status signal for the UI (green / amber / red)
- Operable without external dependencies beyond Anthropic API

## Decision

**Two-step pipeline** in `packages/verifier/`:

### Step 1 — Heuristic verifier (deterministic, O(1) per claim)

`HeuristicVerifier` extracts entities from the claim text (article numbers, percentages, years,
norm identifiers) and checks for their presence in the cited chunk text. It also computes trigram
overlap between claim and chunk.

Verdict matrix:
| entity_match | overlap ≥ 0.2 | Verdict |
|---|---|---|
| ✓ | ✓ | PASSED |
| ✓ | — | PASSED (short claim) or UNCERTAIN |
| — | ✓ | UNCERTAIN |
| — | — | FAILED |

### Step 2 — LLM fallback (Haiku, only for UNCERTAIN claims, parallelized)

`LLMVerifier` calls `claude-haiku-4-5-20251001` for claims where the heuristic returned
UNCERTAIN. Uses the versioned prompt at `docs/prompts/verificador/v1.md`. Calls are run in
parallel via `asyncio.gather` with `run_in_executor`.

Output: `{"verdict": "supported"|"not_supported"|"partial", "reason": "..."}`.

Maps: `supported` → PASSED, `not_supported` → FAILED, `partial` → UNCERTAIN.

### Status policy

| Condition                                            | Status  |
| ---------------------------------------------------- | ------- |
| Any `broken_refs` (REF:n not in mapping)             | `red`   |
| Any FAILED claim                                     | `red`   |
| Any `uncited_claims` (normative claim without REF:n) | `amber` |
| Any UNCERTAIN after LLM fallback                     | `amber` |
| All PASSED, no uncited                               | `green` |

`ClaimExtractor` identifies normative claims using regex patterns for articles, norm names,
legal obligations, jurisprudence, and regulatory bodies.

`CitationParser` detects broken references (REF:n indices that don't resolve to any chunk
in the citation mapping).

## Consequences

**Benefits:**

- Heuristic is deterministic: same input always produces same verdict (reproducible audit log)
- LLM cost is bounded: Haiku is called only for UNCERTAIN claims — typically <20% of claims
- Parallel LLM calls minimize latency overhead for multi-claim responses
- Status is machine-readable: UI can render green/amber/red badge without parsing text

**Trade-offs:**

- Heuristic may miss paraphrased support (trigram overlap is a proxy, not semantic similarity)
- `partial` claims from Haiku remain UNCERTAIN — conservative by design
- Regex patterns are Spanish-language specific; multilingual support requires extension

## Alternatives rejected

| Option                                       | Reason for rejection                                                         |
| -------------------------------------------- | ---------------------------------------------------------------------------- |
| LLM-only verification (all claims via Haiku) | 3-5× higher latency and cost; non-deterministic                              |
| NER + knowledge base lookup                  | High implementation complexity; no marginal accuracy gain vs. entity regex   |
| Embedding similarity (claim vs. chunk)       | Semantic similarity ≠ factual support; no directional verification           |
| Skip verification in MVP                     | Non-negotiable principle: "toda afirmación normativa lleva cita verificable" |
