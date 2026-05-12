# ADR 0028 — Mitigaciones por ausencia de validación experta externa

| Campo      | Valor                      |
| ---------- | -------------------------- |
| Status     | Accepted                   |
| Date       | 2026-05-12                 |
| Authors    | lex-agents team            |
| Supersedes | —                          |
| Relates to | ADR 0009, 0014, 0021, 0027 |

---

## Context

Fase 7 incorporates four significant capability additions: document agents (PDF/DOCX analysis
with `[DOC:s]` citation syntax), a comparative law module (up to 5 jurisdictions, ComparativeView
pivot table), a strict citation verifier that blocks CENDOJ jurisprudential claims with broken
references before response delivery, and CENDOJ as a development-mode source.

None of these additions have undergone formal external expert validation:

- **CGPJ authorization for CENDOJ production use is pending.** CENDOJ is currently integrated
  in dev mode with a hard daily quota cap and no indexing of full jurisprudencia.
- **Commercial legal database licenses (Aranzadi, La Ley, Tirant lo Blanch) have not been
  acquired.** Source coverage remains limited to BOE, EUR-Lex, and CENDOJ-dev.
- **No external jurista has validated the golden dataset.** The 33 golden cases (+ 4 COMP cases)
  used by LeMAJ and adversarial testing were produced internally.
- **Document agent clause analysis is novel.** No external expert has reviewed the extraction
  logic against a representative contract corpus.

Shipping Fase 7 without any mitigation structure would create unacceptable compliance risk for
internal use. Waiting for full external validation would delay internal rollout by an estimated
3–6 months with no clear gate date.

---

## Decision

Ship Fase 7 with a structured set of mitigations that compensate for the absence of external
expert validation, creating a defensible internal deployment. Full expert-validated dataset,
CGPJ formal authorization, and commercial DB integration are deferred to Fase 8.

---

## Mitigations

### M1 — Reinforced caveat banner on every response

Every response rendered in the UI and returned in the API payload carries a three-part caveat
banner:

1. **MVP label**: "Plataforma en fase MVP — uso interno exclusivo."
2. **No-expert-validation warning**: "Sin validación por jurista externo cualificado. Requiere
   revisión humana antes de cualquier uso profesional."
3. **CENDOJ-dev alert** (conditional, when CENDOJ chunks are present in citations):
   "Fuentes CENDOJ en modo desarrollo — cobertura parcial, sin autorización CGPJ de producción."

The banner cannot be dismissed or suppressed by users. It is rendered in the frontend regardless
of verification status (GREEN/AMBER/RED). The API response schema includes `caveat_flags[]` so
downstream integrations cannot accidentally drop the warning.

### M2 — Quick user feedback widget

A three-option inline widget appears on every response:

- **Aceptable** — response is plausible and well-cited.
- **Dudoso** — response raises doubts; user can add a free-text note.
- **Incorrecto** — response contains an identifiable error.

Feedback events are stored in `feedback.db` with `trace_id`, `user_id` (anonymized), timestamp,
verdict, and optional note. The reflection pipeline reads this table as a priority signal
(see M5). Aggregate feedback counts are exposed in Grafana ("Audit & Feedback" panel).

### M3 — Daily audit sampling

A scheduled job runs every day at 23:00 and selects 5 random consultations stratified by:

- **Branch** (each active specialist represented if volume allows).
- **Depth** (at least 1 shallow, 1 standard, 1 deep per day where available).

The sampled consultations appear in the `/auditoria` internal page with status `pending`.
An authorized reviewer (internal compliance team member) opens each record, reviews the
response and citations, and enters a verdict: `correcto`, `dudoso`, or `incorrecto`, plus
optional free-text notes. Results are stored in `audit_samples` table and surfaced in Grafana.

This is an asynchronous process — it does not block query delivery.

### M4 — Unsupported query detector

The query router explicitly rejects four pattern categories with a structured degraded response
rather than attempting a low-confidence answer:

| Category                                 | Pattern examples                                | Degraded response                                                      |
| ---------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------- |
| **Jurisdicción no soportada**            | "derecho chino", "ley federal USA"              | Declares unsupported jurisdiction; lists supported ones.               |
| **Rama jurídica fuera de alcance**       | "derecho de familia", "herencias"               | Declares branch out of scope; lists active branches.                   |
| **Solicitud de actuación procesal**      | "redacta el escrito", "presenta demanda"        | Declares no autonomous procedural action; recommends qualified lawyer. |
| **Consulta sin base normativa indexada** | highly specific facts with no regulatory anchor | Declares inability to ground the answer; lists available sources.      |

Rejected queries are logged with `rejection_reason` for audit purposes. False rejections are
monitored and can trigger prompt evolution via the reflection pipeline.

### M5 — Reflection pipeline prioritizes feedback-negative and audit-incorrecto cases

Before the LeMAJ nightly evaluation run, the reflection pipeline's `failure_analyzer` stage
processes:

1. All feedback events with verdict `dudoso` or `incorrecto` from the previous 24 h.
2. All audit samples with verdict `dudoso` or `incorrecto` that have not yet triggered a
   prompt evolution PR.

These cases are prioritized above LeMAJ failures in the evolution queue. If a prompt evolution
PR is opened, it references the originating `trace_id` and feedback/audit record in the PR body.
Human review remains mandatory before merge (CODEOWNERS + ADR 0021).

### M6 — CENDOJ quota hard cap

`CENDOJ_DAILY_QUOTA` is an environment variable with a hard numerical ceiling. The ingest
pipeline and retriever enforce this cap without exception:

- When the daily quota is exhausted, CENDOJ retrieval falls back to BOE+EUR-Lex only for
  the remainder of the day; no error is surfaced to the user (degraded silently with
  `cendoj_fallback=true` in the response metadata).
- The quota **cannot be raised via configuration change alone**. Any increase requires written
  authorization from the legal team confirming CGPJ approval progress.
- Current quota remaining is exposed as `cendoj_quota_remaining` in `/metrics` (Prometheus gauge).

### M7 — Strict citation verifier blocks broken CENDOJ jurisprudential claims

The citation verifier pipeline (ADR 0008) applies an additional check exclusively for CENDOJ
chunks: if a claim references a CENDOJ-sourced citation and that citation's `ref_id` cannot be
resolved to an indexed chunk (broken reference), the response is **blocked before delivery** and
the API returns a `503 CENDOJ_CITATION_BROKEN` with a user-visible message explaining the
failure. This is stricter than the standard verifier behavior (which downgrades to RED but still
returns the response), reflecting the heightened risk of unverified jurisprudential claims from
a development-mode source.

---

## Consequences

### Positive

- Platform is defensible for internal use: every response clearly communicates its limitations,
  and a structured feedback + audit loop creates continuous improvement pressure.
- Stakeholders have clear documentation of known limitations. This ADR itself serves as
  evidence of deliberate, documented risk management.
- The feedback widget creates a labeled dataset of user-identified errors that directly feeds
  prompt evolution — a real-world signal that golden-case evals alone cannot provide.
- CENDOJ quota cap and strict citation block prevent jurisprudential hallucination risk from
  the development-mode source.

### Negative

- **Higher false-rejection rate from M4**: the unsupported query detector will initially
  over-reject borderline queries until the prompt is calibrated. This requires monitoring and
  targeted prompt evolution cycles.
- **Audit review requires human time**: M3 adds approximately 15–30 minutes per day of
  qualified reviewer time. This must be scheduled and resourced.
- **M7 may surface 503 errors** in cases where CENDOJ indexing is incomplete. Users must be
  briefed to expect occasional CENDOJ unavailability.

### Deferred to Fase 8

- Commercial database licenses (Aranzadi, La Ley, Tirant lo Blanch).
- CGPJ formal authorization for CENDOJ production use and removal of quota cap.
- Expert-validated dataset (≥100 golden cases reviewed by external jurista).
- Document agent clause analysis reviewed by external expert against representative corpus.

---

## Rejected alternatives

### A — Wait for external validation before shipping

Rejected. No external jurista contract is in place. Timeline to expert validation is estimated
at 3–6 months with no hard gate. Internal use would be delayed with no compensating benefit;
the mitigation set above provides a defensible alternative.

### B — Ship Fase 7 without mitigations

Rejected. Shipping without caveat banners, audit sampling, or the unsupported query detector
would expose the platform to misuse and would not meet internal compliance expectations for an
AI-assisted legal tool. The legal team confirmed this is not acceptable.
