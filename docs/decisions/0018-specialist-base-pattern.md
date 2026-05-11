# ADR 0018 — BaseSpecialist Pattern and BRANCH_REGISTRY

**Date**: 2026-05-11  
**Status**: Accepted  
**Deciders**: lex-agents team

---

## Context

Fase 6.2 adds five new legal specialist branches (datos_personales_rgpd, laboral, mercantil_societario, penal_economico, administrativo) alongside the existing regulatorio_bancario_ue_es. All specialists share the same invocation pattern: load a versioned system prompt, call the LLM, parse the text response, compute cost, emit structured logs and OTel spans.

Prior to this ADR, the single specialist was a standalone class with no shared base and no registry. Adding five more would have duplicated ~60 lines of boilerplate per specialist and made the orchestrator depend on concrete class names.

---

## Decision

### BaseSpecialist

All Maker agents inherit from `BaseSpecialist(BaseAgent)` in `core/specialist_base.py`.

**Class-level declarations** (ClassVars, not instance attrs):

```python
class BaseSpecialist(BaseAgent):
    branch_id: ClassVar[str]           # e.g. "laboral"
    prompt_name: ClassVar[str]         # e.g. "especialistas/laboral"
    prompt_version: ClassVar[int] = 1
```

**Interface**:

- `run_async(query, assembled, trace_id, sub_task=None) → AgentResponse` — abstract async method all subclasses implement
- `run(query, assembled, trace_id) → AgentResponse` — sync shim using `asyncio.run()` to satisfy the `BaseAgent` ABC; safe to call from synchronous contexts
- `_invoke(query, assembled, trace_id, span_name=None, extra_caveat=None) → AgentResponse` — shared helper with OTel tracing, cost accounting, empty-response guard, and structured logging

**Why `asyncio.run()` and not `asyncio.get_event_loop().run_until_complete()`**: The latter raises `RuntimeError: This event loop is already running` when called from any async context (FastAPI routes, pytest-asyncio). `asyncio.run()` creates a fresh event loop each time and is safe everywhere.

**Empty-response guard**: `_invoke` searches for the first `type=="text"` block in the response content list rather than indexing `[0]`. If no text block is present (empty stop, tool_use block, etc.) it logs an error and returns a fallback message rather than raising `IndexError`.

### BRANCH_REGISTRY

`routing/branch_classifier.py` exposes a single function:

```python
def get_specialist_class(branch_id: str) -> type[BaseSpecialist]: ...
```

The registry dict is built lazily on first call (imports are expensive if the package is imported in non-agent contexts). The module-level `_REGISTRY` variable is populated once and re-used on subsequent calls.

**8-step recipe for adding a new specialist branch**:

1. Create `specialists/<branch_id>.py` inheriting `BaseSpecialist`
2. Set `branch_id`, `prompt_name`, `prompt_version` ClassVars
3. Implement `run_async()` — call `self._invoke(...)`, optionally append domain-specific caveats
4. Create `docs/prompts/especialistas/<branch_id>/v1.md` with YAML frontmatter
5. Register the class in `routing/branch_classifier.py`
6. Extend `router_v1.py` tool schema to include the new branch name
7. Add a smoke test in `tests/test_specialists.py`
8. Add a YAML entry to `docs/prompts/router/v2.md` describing the routing condition

### Special case: penal_economico

`PenalEconomicoAgent` always appends `⚠️ AVISO LEGAL` to the answer and passes `_PENAL_CAVEAT` as `extra_caveat` to `_invoke`. This is non-negotiable: the penal branch must never be used as a substitute for a qualified defense lawyer.

---

## Consequences

**Positive**:

- Adding a new branch is ~30 lines of code plus a prompt file
- All cross-cutting concerns (cost, tracing, logging, empty-response guard) are in one place
- Orchestrator and Coordinator use `get_specialist_class(branch_id)` with no static imports of specialist classes

**Negative**:

- Lazy registry initialization is not thread-safe under highly concurrent initialization (mitigated by CPython GIL; will be addressed if switching to multi-process workers)
- `asyncio.run()` in the sync shim creates a new event loop per call — acceptable overhead for infrequent sync call sites, but callers should prefer `run_async()` directly

---

## Alternatives considered

**Inheritance hierarchy per legal domain**: rejected — domains have identical invocation patterns; only system prompts differ.

**Plugin-based autodiscovery (importlib)**: rejected for MVP — explicit registration in `branch_classifier.py` is easier to audit and refactor.
