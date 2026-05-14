# ADR 0050 — Secrets Rotation Strategy

**Status:** Accepted
**Date:** 2026-05-14
**Decisores:** Ignacio Bernal (Santander)
**ADRs relacionados:** 0034 (audit trail immutable), 0042 (persistence), 0044 (DORA controls)
**Sub-fase:** 9.4

---

## Context

Fase 9.2 created five Secrets Manager secrets but deferred rotation because CDK's L2
`addRotationSingleUser()` introduces a cyclic dependency between `DataStack` and
`NetworkSpokeStack` via Aurora's `Endpoint.Port` token. Without rotation, the setup
does not satisfy DORA Art. 9(4)(c) requirements for credential lifecycle management.

This ADR defines the rotation schedule, strategy per secret type, and the CDK pattern
that avoids the cycle.

---

## Decision

### CDK cycle fix

The cycle originates from `addRotationSingleUser()` calling
`connections.allowDefaultPortFrom(rotationLambda)`, which resolves
`AuroraCluster/Resource.Endpoint.Port` — a cross-stack token owned by NetworkSpokeStack.

**Fix**: use `CfnRotationSchedule` (L1) directly with an explicit `HostedRotationLambda`
reference. The rotation Lambda's security group is created inside DataStack (not via
`Connections`), and the port is hardcoded to `5432` (Aurora PostgreSQL always uses 5432).
This removes all cross-stack token references from the rotation configuration.

```typescript
// data.ts — safe rotation without CDK cycle
const rotationLambdaSg = new ec2.SecurityGroup(this, 'SgRotationLambda', {
  vpc: networkStack.vpc,
  description: 'Secrets Manager rotation Lambda for Aurora app-user',
  allowAllOutbound: false,
});
rotationLambdaSg.addEgressRule(
  ec2.Peer.securityGroupId(networkStack.sgAurora.securityGroupId),
  ec2.Port.tcp(5432),
);

new secretsmanager.CfnRotationSchedule(this, 'AppUserRotation', {
  secretId: this.dbAppUserSecret.secretArn,
  hostedRotationLambda: {
    rotationType: 'PostgreSQLSingleUser',
    vpcSecurityGroupIds: rotationLambdaSg.securityGroupId,
    vpcSubnetIds: networkStack.vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }).subnetIds.join(','),
  },
  rotationRules: { automaticallyAfterDays: 30 },
});
```

### Rotation schedule per secret

| Secret | Path | Strategy | Rotation period | Grace period |
|---|---|---|---|---|
| Aurora app-user | `/lex-agents/${env}/db/app-user` | AWS-managed Lambda (PostgreSQL single-user) | 30 days | None (atomic swap) |
| JWT signing key | `/lex-agents/${env}/jwt/signing-key` | Custom Lambda | 90 days | 24h overlap window |
| Anthropic API key | `/lex-agents/${env}/anthropic/api-key` | Manual | Alert if > 90 days | N/A |
| Langfuse secret-key | `/lex-agents/${env}/langfuse/secret-key` | Manual | Alert if > 90 days | N/A |
| INLABS token | `/lex-agents/${env}/inlabs/token` | Manual (Imprensa Nacional) | As required by source | N/A |

### Aurora app-user rotation (dual-password strategy)

AWS-managed `PostgreSQLSingleUser` rotation Lambda:
1. Generates new password.
2. Updates the Postgres user's password in Aurora.
3. Updates the secret value in Secrets Manager.
4. Verifies connectivity.

No application downtime because the app always reads the secret at startup / on
`secretsmanager:GetSecretValue` with `VersionStage=AWSCURRENT`. Between steps 2 and 3
there is a brief window (<1s) where old password is in Postgres but new password is
not yet in Secrets Manager — mitigated by the `AWSPENDING` staging label pattern built
into the AWS rotation Lambda.

### JWT signing key rotation (grace period strategy)

Custom rotation Lambda (`packages/pipeline_aws/src/lex_pipeline_aws/jwt_rotation/`):
1. Generates new 256-bit signing key; stores as `AWSPENDING` in Secrets Manager.
2. Updates API environment variable `JWT_SIGNING_KEY_NEW` (read from `AWSPENDING`).
3. API accepts tokens signed by both `AWSCURRENT` and `AWSPENDING` during grace period.
4. After 24h, Lambda promotes `AWSPENDING` → `AWSCURRENT`, removes `AWSPREVIOUS`.
5. API stops accepting old tokens.

Application code changes required (Fase 9.4): `apps/api` JWT validation must check
both `AWSCURRENT` and `AWSPENDING` versions during rotation.

### Manual secrets alerting

A CloudWatch Events rule fires daily and checks the `LastRotatedDate` of manual secrets.
If a manual secret has not been rotated in > 90 days, a CloudWatch alarm triggers the
SNS alerts topic with severity `WARN`.

Implemented as a Lambda `lex-agents-${env}-secret-age-check` scheduled at `cron(0 8 * * ? *)`.

---

## Consequences

### Positive
- DORA Art. 9(4)(c) credential lifecycle management satisfied.
- Aurora rotation is fully automated, zero-downtime.
- JWT rotation grace period eliminates forced logout of active users during rotation.
- CDK cycle eliminated; `DataStack` tests remain cycle-free.

### Negative / mitigations
- **Custom JWT rotation Lambda**: additional Lambda to maintain. Mitigated by
  keeping it minimal (<100 lines) with comprehensive unit tests.
- **Manual secret alerting**: Anthropic and INLABS keys still require human action.
  Mitigated by daily check + alarm; documented in ops runbook.

---

## DORA mapping

| Control | Article | How this ADR satisfies it |
|---|---|---|
| Credential lifecycle | Art. 9(4)(c) | Automated 30-day Aurora rotation + 90-day JWT rotation |
| Access control reviews | Art. 9(4)(a) | Rotation ensures stale credentials are invalidated |
| Audit of key changes | Art. 10(1) | All `secretsmanager:RotateSecret` API calls captured by CloudTrail (ADR 0044) |
