# Roadmap — Fase 8

> Date: 2026-05-12
> This document describes the planned scope, gate conditions, and estimated effort for Fase 8
> of the lex-agents platform. Fase 7 ships with the mitigation set documented in ADR 0028.
> Fase 8 resolves the structural gaps that mitigations compensate for.

---

## 1. Prerequisitos bloqueantes

These are hard gates. No Fase 8 item that depends on them can be started until they are cleared.

### P1 — Contrato con jurista externo

**What it is:** A formal services contract with a qualified external jurista (Spanish-qualified,
banking and EU regulatory specialization) to validate the platform dataset and review document
agent outputs.

**Why deferred:** No budget allocation or vendor selection was completed during Fase 7.
Identifying the right profile (banking regulation + RGPD + data law) takes time.

**Gate condition:** Signed contract, NDA executed, access to internal platform granted.

**Estimated effort:** S (contracting process, not engineering).

**Gates items:** P1 gates items 2 (expert dataset validation), 5 (drafting agents).

---

### P2 — Autorización CGPJ para CENDOJ producción

**What it is:** Formal written authorization from the Consejo General del Poder Judicial to use
CENDOJ data in a production AI-assisted legal platform, beyond the development-mode access
currently in place.

**Why deferred:** CGPJ authorization process was initiated during Fase 6. No response received
as of Fase 7 release. The process is external and timeline is not controlled by the team.

**Gate condition:** Written CGPJ authorization document received and reviewed by legal team.

**Estimated effort:** S (administrative, not engineering).

**Gates items:** P2 gates item 3 (CENDOJ producción).

---

### P3 — Licencias de bases de datos comerciales

**What it is:** Signed license agreements with one or more of: Aranzadi (Thomson Reuters),
La Ley (Wolters Kluwer), Tirant lo Blanch. Each license grants API or bulk-download access
to their legal document corpus.

**Why deferred:** Budget and procurement review not completed during Fase 7. Adapters are already
prepared in `packages/pipeline/src/lex_agents_pipeline/adapters/` pending license acquisition.

**Gate condition:** Signed license agreement(s) received; API credentials or data delivery
confirmed.

**Estimated effort:** S (procurement, not engineering; adapter code already prepared).

**Gates items:** P3 gates item 4 (bases de datos comerciales).

---

## 2. Validación experta del dataset

**What it is:** An external jurista (contracted via P1) reviews and validates the 33 existing
golden evaluation cases plus the 4 comparative law (COMP) cases. For each case, the jurista
confirms or corrects: the expected answer, the normative citations, the stated divergences, and
the caveat language. The validated dataset then becomes the authoritative source for LeMAJ and
adversarial testing. The second phase extends to 100+ validated cases across all 6 branches.

**Why deferred:** Requires P1 (jurista contract). Internal production of cases was sufficient for
Fase 7 MVP; external validation is required before the platform is used for higher-stakes internal
decisions.

**Gate condition for Phase 1 (33+4 cases):** P1 cleared; jurista completes review of all existing
cases with documented verdict per case.

**Gate condition for Phase 2 (100+ cases):** Phase 1 complete; jurista reviews additional cases
covering all 6 branches, at least 2 jurisdictions per branch, and all 3 depth levels.

**Estimated effort:** M (Phase 1: ~3 weeks jurista time + 1 week engineering for tooling);
L (Phase 2: ~6 weeks jurista time + iterative engineering).

---

## 3. CENDOJ producción

**What it is:** After CGPJ formal authorization (P2), the CENDOJ integration is upgraded from
development mode to production:
- `CENDOJ_DAILY_QUOTA` hard cap is removed.
- Full jurisprudencia index is built (Tribunal Supremo, Audiencias Provinciales, Tribunal
  Constitucional relevant chambers).
- CENDOJ source is promoted from "fuentes en desarrollo" to primary source in `docs/limitations.md`.
- The strict pre-delivery citation block (ADR 0028 M7) is retained but the fallback behavior
  changes from silent degradation to surfaced partial response.

**Why deferred:** CGPJ authorization (P2) is externally gated. Engineering work can be prepared
in parallel (indexer, quota removal, Dagster asset), but production activation requires P2.

**Gate condition:** P2 cleared; full ingest passes GREEN gate (≥1000 documents, VerifierPipeline
confirms no systematic broken-ref rate above 1%).

**Estimated effort:** M (indexer scale-up, quota removal, Dagster asset promotion, eval update).

---

## 4. Bases de datos comerciales

**What it is:** Integration of one or more commercial legal databases — Aranzadi, La Ley, or
Tirant lo Blanch — as additional indexed sources. Each integration adds a Dagster source asset,
a scraper/adapter (stubs already in `packages/pipeline/src/lex_agents_pipeline/adapters/`),
chunking and embedding pipeline, and corresponding Qdrant collection updates.

Priority order: Aranzadi (broadest ES+EU banking coverage) > La Ley > Tirant lo Blanch.

**Why deferred:** License acquisition (P3) is externally gated. Adapter code is already prepared,
reducing engineering effort once licenses arrive.

**Gate condition:** P3 cleared for target DB; full ingest passes GREEN gate per the 8-step
checklist in `docs/runbook.md` (section "Abrir nueva fuente documental").

**Estimated effort:** S per DB (adapters prepared; mainly configuration, ingest validation,
and eval update to cover new citation formats).

---

## 5. Drafting agents

**What it is:** Specialist agents that assist in drafting contractual clauses (e.g., externalización
clauses, data processing agreements, MREL-linked covenants). Drafting agents operate in
human-in-the-loop mode only: they propose draft text, mark it as AI-generated, and require
a qualified lawyer to review and sign off before any clause is used.

Autonomous drafting without a human review gate is explicitly not in scope — not in Fase 8,
not in any planned fase.

**Why deferred:** Requires P1 (expert validation). Drafting agents that produce incorrect clause
text without validated evaluation criteria would be higher risk than the current analysis-only
agents. A validated dataset covering drafting quality is a prerequisite.

**Gate condition:** P1 cleared; expert-validated dataset includes at least 20 drafting evaluation
cases; human-in-the-loop review UI implemented and tested.

**Estimated effort:** L (new agent type, UI review flow, eval cases, expert validation cycle).

---

## 6. Confidence calibration

**What it is:** Per-claim confidence scores exposed alongside existing citation verification
(GREEN/AMBER/RED). Each normative claim in a response carries a numerical confidence score
derived from the heuristic verifier's entity-match and trigram-overlap metrics, calibrated
against the expert-validated dataset. Uncertainty quantification is added to the LeMAJ panel
output.

**Why deferred:** Calibration requires the expert-validated dataset (item 2) to be meaningful.
Calibrating against internally-produced cases would produce misleading confidence scores.

**Gate condition:** Expert-validated dataset (item 2, Phase 1) complete; calibration curve
validated on held-out cases with Brier score < 0.15.

**Estimated effort:** M (verifier extension, calibration pipeline, UI score display, eval update).

---

## 7. Agentes proactivos

**What it is:** Asynchronous monitoring agents that watch BOE and EUR-Lex feeds for regulatory
changes relevant to active query branches, and push notifications to subscribed users. Examples:
new Circular BdE published, CRR amendment entering into force, EBA consultation open.

Notifications are asynchronous — they do not affect the query path. Users configure subscription
topics per branch and jurisdiction.

**Why deferred:** Proactive agents require a persistent notification infrastructure (WebSocket
or email), user subscription management, and a feed-diff mechanism for regulatory changes.
These are non-trivial additions that are not needed for the MVP query use case.

**Gate condition:** No external gate. Internal engineering gate: notification infrastructure
implemented and tested; false-positive rate on regulatory change detection < 5% on 30-day
backtest.

**Estimated effort:** L (feed-diff pipeline, notification infra, subscription UI, backtesting).

---

## 8. Memoria episódica

**What it is:** Per-user episodic memory that retains the context of previous consultations
(query, branch, key citations, verdict) to inform future queries in the same topic area.
Memory entries are governed by a RGPD-compliant retention policy: configurable TTL (default
30 days), user-initiated deletion, and no cross-user data sharing.

**Why deferred:** Retention policy requires DPO approval (ADR 0013 documents this dependency).
The policy was not approved during Fase 7. Engineering design is complete; implementation
is blocked on approval.

**Gate condition:** DPO approval of retention policy documented in writing; RGPD-compliant
storage backend selected and reviewed; user deletion flow implemented and tested.

**Estimated effort:** M (storage backend, retention enforcement, deletion UI, DPO review cycle).

---

## 9. Despliegue corporativo

**What it is:** Migration from the current Docker Compose + local deployment to a Santander
corporate infrastructure deployment:
- **SSO Santander**: replace current JWT username/password auth with Santander corporate SSO
  (SAML or OIDC). Remove `AUTH_USERS_JSON` env var; user management via corporate directory.
- **IT security review**: formal IT security review of the platform by Santander IT Security
  team, covering API security, data flows, secret management, and dependency audit.
- **On-prem inference option**: evaluate feasibility of on-premises LLM inference for
  data-residency-sensitive queries, reducing reliance on Anthropic API for the most
  sensitive content.

**Why deferred:** SSO integration requires IT team engagement and corporate SAML/OIDC endpoint
access not yet provisioned. IT security review requires platform stability (Fase 7 is the
first release candidate). On-prem inference feasibility depends on hardware availability.

**Gate condition:** IT team engagement confirmed; SSO endpoint provisioned; IT security review
scheduled.

**Estimated effort:** M (SSO: 2 weeks engineering + IT coordination); L (on-prem inference,
if approved: hardware + model serving + performance validation).

---

## 10. Fase 8 acceptance criteria

Fase 8 is considered complete when ALL of the following are met:

| Criterion | Target | Gate |
|---|---|---|
| Expert-validated dataset | ≥ 100 golden cases reviewed by external jurista | P1 + item 2 |
| CENDOJ producción | CGPJ authorization received; full jurisprudencia index active | P2 + item 3 |
| At least 1 commercial DB | Aranzadi, La Ley, or Tirant integrated and GREEN-gated | P3 + item 4 |
| Confidence calibration | Brier score < 0.15 on held-out validated cases | Item 6 |
| Corporate SSO | Santander SSO replaces username/password auth | Item 9 |
| IT security review | Formal sign-off from Santander IT Security | Item 9 |

Items 5 (drafting agents), 7 (agentes proactivos), 8 (memoria episódica), and on-prem inference
(item 9 sub-item) are Fase 8 stretch goals — desirable but not blocking Fase 8 completion.
