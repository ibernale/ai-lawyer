# ADR 0049 — Multi-Source Pipeline Factory (per-source Step Functions state machines)

**Status:** Accepted
**Date:** 2026-05-14
**Decisores:** Ignacio Bernal (Santander)
**ADRs relacionados:** 0006 (source strategy), 0047 (Dagster → Step Functions), 0043 (CDK)
**Sub-fase:** 9.4

---

## Context

ADR 0047 introduced a single Step Functions state machine for BOE + EUR-Lex ingestion
(Fase 9.2). Fase 9.4 must scale to 13 sources with different schedules, fetch strategies,
parse complexity, and operational concerns (e.g., CENDOJ quota management).

The options are:

| Option | Description |
|---|---|
| A | One monolithic state machine with `Choice` branches per source |
| B | One state machine per source, created via a CDK factory construct |

### Option A — Monolithic state machine

- Pro: single execution history view, one EventBridge rule.
- Contra: a failure in one source blocks others if not carefully isolated; state
  explosion with 13 Choice branches; impossible to trigger a single source independently;
  impossible to tune ACU/memory per source.

### Option B — Per-source state machine (selected)

- Pro: independent execution, independent retry policy, independent schedule, independent
  CloudWatch metrics per source; `cdk diff` shows exactly which source changed.
- Contra: 13+ state machines in the CloudFormation template. Mitigated by a CDK
  `SourcePipeline` construct that encapsulates all boilerplate per source.

---

## Decision

**Option B: one Step Functions state machine per source, created by a reusable
`SourcePipeline` CDK L3 construct.**

### Source catalogue (Fase 9.4)

| Source | Status | Schedule (UTC) | Trigger | Fetch runtime |
|---|---|---|---|---|
| `boe` | GREEN | `cron(0 7 * * ? *)` | EventBridge | Lambda |
| `eur_lex` | GREEN | `cron(0 6 ? * MON *)` | EventBridge | Lambda |
| `aepd` | GREEN | `cron(0 6 ? * FRI *)` | EventBridge | Lambda |
| `edpb` | GREEN | `cron(0 6 ? * MON *)` | EventBridge | Lambda |
| `bde` | GREEN | `cron(0 7 * * ? *)` | EventBridge | Lambda |
| `eba` | GREEN | `cron(0 6 ? * MON *)` | EventBridge | Lambda |
| `esma` | GREEN | `cron(0 6 ? * MON *)` | EventBridge | Lambda |
| `legislation_uk` | GREEN | `cron(0 6 ? * MON *)` | EventBridge | Lambda |
| `fca` | GREEN | `cron(0 6 ? * MON *)` | EventBridge | Lambda |
| `tribunal_constitucional` | AMBER | `cron(0 6 ? * MON *)` | EventBridge (disabled) | Lambda |
| `cendoj` | AMBER | *(manual only)* | `workflow_dispatch` or console | Lambda + quota check |
| `inlabs` | STUB | `cron(0 4 * * ? *)` | EventBridge | Lambda (stub) |
| `sidof` | STUB | `cron(0 13 * * ? *)` | EventBridge | Lambda (stub) |

AMBER sources: EventBridge rule created but `State: DISABLED`. Activation via CDK context
key `lexAgents:enable${PascalSource}Pipeline: true`.

STUB sources: Lambda handler returns immediately with `{"status": "stub_not_implemented"}`;
state machine and schedule created so infrastructure is ready for implementation.

### SourcePipeline construct

```typescript
// infra/cdk/lib/constructs/source-pipeline.ts
interface SourcePipelineProps {
  source: string;                // e.g. "boe", "eur_lex"
  schedule?: events.Schedule;    // undefined = manual only
  scheduleEnabled?: boolean;     // default true; false for AMBER
  fetchRawFn: lambda.IFunction;
  parseCanonicalFn: lambda.IFunction;
  chunkDocumentFn: lambda.IFunction;
  contextualizeChunksFn: lambda.IFunction;
  appServicesStack: AppServicesStack;  // for ECS RunTask ARN
  vpc: ec2.IVpc;
  sfnRole: iam.IRole;            // shared across all state machines
  alertTopic: sns.ITopic;
}
```

Each `SourcePipeline` creates:
1. `CfnStateMachine` — 8-state ASL (identical structure to Fase 9.2)
2. `events.Rule` — EventBridge schedule (if `schedule` provided)
3. `CloudWatch.Alarm` — execution failure alarm → `alertTopic`

CENDOJ additionally creates:
- `check_quota` Lambda step as the first state
- `decrement_quota` Lambda step after each successful document fetch
- DynamoDB `QuotaTracker` table (shared across CENDOJ state machine executions)

### Format change sensor

A separate Lambda `lex-agents-${env}-format-sensor` runs on `rate(1 hour)`:
- Makes HTTP HEAD requests to each source's canonical URL
- Compares `ETag` / `Last-Modified` / content-length hash against DynamoDB
  `lex-agents-${env}-format-fingerprints` table
- On change: puts CloudWatch metric `FormatChangeDetected` + opens GitHub issue
  via OIDC token (scoped to `issues: write`)

### Lambda handler layout

```
packages/pipeline_aws/src/lex_pipeline_aws/
├── fetch_raw/        # BOE (existing)
├── parse_canonical/  # BOE (existing)
├── chunk_document/   # generic (existing)
├── contextualize_chunks/ # generic (existing)
├── sources/
│   ├── boe/          # fetch_raw + parse_canonical handlers
│   ├── eur_lex/
│   ├── aepd/
│   ├── edpb/
│   ├── bde/
│   ├── eba/
│   ├── esma/
│   ├── legislation_uk/
│   ├── fca/
│   ├── tribunal_constitucional/
│   ├── cendoj/       # + check_quota + decrement_quota
│   ├── inlabs/       # stubs
│   └── sidof/        # stubs
└── format_sensor/    # hourly format change detector
```

Each source's `fetch_raw/handler.py` imports from `packages/ingest/sources/<source>.py`
(existing scrapers — no code duplication).

---

## Consequences

### Positive
- Each source pipeable independently; a CENDOJ quota block does not affect EUR-Lex.
- CDK `SourcePipeline` construct means adding a new source is ~10 lines in `pipelines.ts`.
- AMBER/STUB sources have infra pre-provisioned; activation is one CDK context flag.
- Per-source CloudWatch alarms enable precise paging.

### Negative / mitigations
- **13+ state machines in CloudFormation**: template grows. CloudFormation limit is
  500 resources per stack; PipelinesStack at ~13 sources × ~15 resources ≈ 195 resources —
  well within limit. Monitor with `cdk synth | grep -c '"Type"'`.
- **Lambda cold starts per source**: each source has 4 Lambda functions = 52 Lambdas total.
  Mitigated by: (a) provisioned concurrency not needed at daily frequency; (b) Lambda
  SnapStart for Python 3.12 (available in eu-central-1).

---

## Alternatives considered

| Option | Reason rejected |
|---|---|
| Monolithic state machine | Source isolation, operational clarity (see above) |
| Reuse existing `packages/pipeline/` Dagster assets | Dagster daemon cost + complexity (ADR 0047) |
| AWS Glue workflows | Glue is ETL-focused; overkill for HTTP-fetch pipelines; Step Functions tighter AWS integration |
