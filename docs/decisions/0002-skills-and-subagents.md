# 0002 — Skills y subagents como alternativa al CLAUDE.md monolítico

**Status:** Accepted
**Date:** 2026-05-10

## Context

Claude Code reads `CLAUDE.md` at the root of the repository as the primary
source of project context. As projects grow, a single monolithic CLAUDE.md
becomes unwieldy: it either grows too large to be useful (exceeding useful
context budget) or stays too brief to be actionable. lex-agents has multiple
specialist domains (legal style, ingestion, RAG, verification, evals, DevOps)
each with detailed conventions that would bloat a single file.

Claude Code also supports two additional primitives:
- **Skills** (`.claude/skills/<name>/SKILL.md`): reusable instruction sets
  activated on demand by name or by task-matching.
- **Subagents** (`.claude/agents/<name>.md`): specialised agents with their
  own system prompt, tool set, and model, invoked by the main agent for
  delegated tasks.

## Decision

We adopt a three-level context architecture:

### Level 1: CLAUDE.md (≤ 30 lines)
Contains only: project identity, non-negotiable principles (3 items),
stack summary (1 line), language convention, and pointers to where to
find more. Never grows beyond one screen.

### Level 2: Skills (8 skills, each < 5k tokens)
Domain-specific instruction sets loaded on demand. Each skill covers one
coherent concern: legal style, chunking, citation format, prompt versioning,
eval running, source ingestion, security/PII, project conventions. Skills
are activated by task relevance — Claude Code matches the task description
against skill `description` frontmatter.

This follows the principle of **context on demand**: load detailed
instructions only when the task requires them, preserving context window
budget for code and artifacts.

### Level 3: Subagents (6 agents, each a specialist)
For tasks that are complex enough to benefit from delegation — prompt
engineering, scraper repair, verification pipeline development, eval
authoring, code review, DevOps — we spawn a dedicated subagent with:
- A tailored system prompt (role, checklist, output format)
- A restricted tool set (read-only for reviewer; write access for implementers)
- The appropriate model (opus for legal/verification reasoning; sonnet for
  engineering; haiku not used as a subagent in Fase 0)

Subagent delegation has two benefits:
1. **Isolation**: the specialist's context is not polluted by unrelated code
2. **Parallelism**: multiple subagents can run concurrently (Fase 3+)

## Rationale for this approach

The Anthropic Model Specification and Claude Code documentation recommend
keeping CLAUDE.md focused and using skills/agents for specialisation. This
mirrors the software engineering principle of separation of concerns: a
1000-line CLAUDE.md is as undesirable as a 1000-line function.

Skills map to the "few-shot + instruction" prompting pattern: providing
a skill is equivalent to prepending highly relevant instructions to the
context only when needed.

Subagents map to the orchestrator-worker pattern documented in Anthropic's
multi-agent guidance: the main agent (orchestrator) delegates to specialists
(workers) who have narrower context, tighter tools, and clearer output
contracts.

## Consequences

- New domains (e.g., laboral, contencioso) → new skill + new subagent.
  CLAUDE.md never changes.
- Skill maintenance: each skill is owned by the team responsible for that
  domain. Skills are versioned via git like any other file.
- Subagent model selection must be reviewed when Anthropic releases new
  model generations (reference ADR 0001 for model selection rationale).

## Alternatives considered

| Alternative | Rejected because |
|-------------|-----------------|
| Single 2000-line CLAUDE.md | Context budget waste; hard to maintain; no specialisation |
| LangGraph / CrewAI agent frameworks | External dependency; bypasses Claude Code's native agent primitives |
| Per-file inline instructions | Not persistent; must be repeated; no reuse across tasks |
