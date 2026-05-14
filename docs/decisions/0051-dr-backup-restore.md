# ADR 0051 — Disaster Recovery Strategy: Backup-Restore to eu-west-1

**Status:** Accepted
**Date:** 2026-05-14
**Decisores:** Ignacio Bernal (Santander)
**ADRs relacionados:** 0036 (regions), 0037 (multi-account), 0042 (persistence), 0044 (DORA controls)
**Sub-fase:** 9.4

---

## Context

Fase 9.1–9.3 established the primary workload in eu-central-1 (Frankfurt). DORA Art. 12
requires financial entities to have tested ICT business continuity plans with defined
RPO and RTO targets. The platform currently has no DR capability.

Three DR tiers were considered:

| Tier | Description | RTO | RPO | Monthly cost |
|---|---|---|---|---|
| **Backup-Restore** | Periodic backups replicated cross-region; restore on DR event | 4–8h | 24h | ~$30–50/month |
| **Pilot Light** | Minimal infrastructure running in eu-west-1; scale up on event | 1–2h | 1h | ~$200–400/month |
| **Warm Standby** | Full-capacity replica always running | 15–30min | 5min | ~$800–1200/month |

For the development phase (Fase 9), cost justification for Pilot Light or Warm Standby
does not exist. Backup-Restore satisfies DORA requirements for non-production environments
and establishes the runbook infrastructure that will be promoted to Pilot Light at
production launch (Fase 10).

---

## Decision

**Backup-Restore tier for Fase 9 dev environment. Target: eu-west-1 (Ireland).**

### RPO / RTO targets

| Environment | RPO | RTO |
|---|---|---|
| Dev (Fase 9) | 24h | 8h |
| Staging (Fase 9.5) | 4h | 4h |
| Production (Fase 10) | 1h | 2h (Pilot Light) |

### Aurora Serverless v2 backup

**Automated backups** (already enabled in DataStack with 7-day retention):
- `backupRetentionPeriod: 7` covers point-in-time recovery within the retention window.
- Cross-region: AWS Backup `BackupPlan` copies Aurora snapshots to eu-west-1.
  Retention: 30 days in eu-west-1.

**AWS Backup configuration** (in DataStack):
```typescript
const backupPlan = new backup.BackupPlan(this, 'AuroraBackupPlan', {
  backupPlanName: `lex-agents-${envName}-aurora-dr`,
  backupPlanRules: [
    backup.BackupPlanRule.daily({
      completionWindow: Duration.hours(2),
      startWindow: Duration.hours(1),
      deleteAfter: Duration.days(7),
      copyActions: [{
        destinationBackupVault: backup.BackupVault.fromBackupVaultArn(
          this, 'DrVault',
          `arn:aws:backup:${DR_REGION}:${this.account}:backup-vault:lex-agents-${envName}-dr`,
        ),
        deleteAfter: Duration.days(30),
      }],
    }),
  ],
});
backupPlan.addSelection('AuroraSelection', {
  resources: [backup.BackupResource.fromRdsDatabaseCluster(this.aurora)],
});
```

The DR backup vault in eu-west-1 must be pre-created (bootstrapped separately as it
requires a separate CloudFormation stack in eu-west-1). Documented in `docs/aws/dr-plan.md`.

### S3 cross-region replication (CRR)

S3 CRR enabled on three buckets in DataStack:
- `lex-agents-raw-${env}` → replica in eu-west-1
- `lex-agents-canonical-${env}` → replica in eu-west-1
- `lex-agents-backups-${env}` → replica in eu-west-1

`lex-agents-evals-${env}` excluded from CRR (eval fixtures are reproducible; cost
of replication not justified).

CRR rule: all objects, `StorageClass: STANDARD_IA` in replica (cost optimisation).
Replication time: eventual (S3 SLA 99.99% within 15 min for standard objects,
guaranteed via S3 Replication Time Control if SLA is required — not enabled in dev).

### GitHub Actions / CDK

The CDK application is fully reproducible from code. No DR procedure required for infra
code — redeploy from `main` branch on a fresh account. OIDC role setup is documented
in ADR 0043 and `docs/aws/account-bootstrap.md`.

### Langfuse traces

Langfuse Aurora cluster (`LangfuseStack`) is included in the same AWS Backup plan.
Langfuse S3 export (migration scripts from ADR 0048) also stored in the backups bucket
(covered by CRR above).

---

## DR Runbook location

`docs/aws/dr-plan.md` — step-by-step procedure including:
1. DR trigger criteria (detection, escalation, decision matrix)
2. Aurora restore from eu-west-1 snapshot
3. S3 replication verification
4. DNS / ALB cutover (Route 53 failover record)
5. Smoke test checklist
6. Rollback to primary

---

## Consequences

### Positive
- DORA Art. 12 (business continuity) satisfied for dev phase with documented RPO/RTO.
- AWS Backup + S3 CRR are fully managed; minimal operational overhead.
- Runbook established now; promotion to Pilot Light at Fase 10 requires adding
  infrastructure resources to eu-west-1, not rewriting procedures.

### Negative / mitigations
- **24h RPO in dev**: acceptable given dev data is largely reproducible (re-ingest
  from sources). User consultation data is the only non-reproducible asset;
  7-day automated Aurora backups provide intra-region PITR.
- **8h RTO in dev**: acceptable for a dev environment. Documented explicitly so
  stakeholders have clear expectations.
- **DR vault pre-creation**: the eu-west-1 backup vault must be bootstrapped before
  the first backup runs. Documented in `docs/aws/dr-plan.md` and `account-bootstrap.md`.

---

## Upgrade path to Pilot Light (Fase 10)

1. Create `NetworkSpokeStack` in eu-west-1 (minimal VPC, no NAT by default).
2. Create minimal `DataStack` in eu-west-1 (Aurora cluster stopped, S3 buckets exist).
3. Create `AppServicesStack` in eu-west-1 with 0 desired tasks.
4. On DR event: `aws rds restore-db-cluster-from-snapshot`, scale ECS tasks to 1,
   update Route 53 failover record.
5. RTO target: 1–2h.
