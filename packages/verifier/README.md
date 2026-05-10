# packages/verifier

Claim-level citation verifier for lex-agents. Given a generated response and
the retrieved chunk mapping, it checks that each [REF:n] annotation genuinely
supports the claim it backs — not just that the chunk exists. Uses a two-step
approach: deterministic heuristic pass (exact quote matching, date consistency)
followed by an LLM fallback with claude-haiku-4-5 for semantic entailment.
Returns a typed `VerificationReport` with per-claim verdicts.
