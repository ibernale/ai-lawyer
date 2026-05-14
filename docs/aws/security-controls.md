# Security Controls — lex-agents AWS (Fase 9)

## KMS Customer Managed Keys

| Alias | Stack | Key Users | Rotation |
|-------|-------|-----------|---------|
| `lex-agents-dev-rds` | KmsStack | Aurora cluster, Performance Insights | Annual (auto) |
| `lex-agents-dev-s3` | KmsStack | S3 buckets (raw, canonical, evals, backups, compliance) | Annual (auto) |
| `lex-agents-dev-secrets` | KmsStack | Secrets Manager secrets | Annual (auto) |
| `lex-agents-dev-logs` | KmsStack | CloudWatch Log Groups, CloudTrail | Annual (auto) |
| `lex-agents-dev-ebs` | KmsStack | EBS volumes (reserved) | Annual (auto) |
| `security-account-key` | SecurityBaselineStack | SNS, CloudWatch Logs (security acct) | Annual (auto) |

All CMKs have `enableKeyRotation: true` and `pendingWindow: 30 days`.

---

## Security Groups

| SG Name | Stack | Purpose | Ingress | Egress |
|---------|-------|---------|---------|--------|
| `lex-agents-dev-alb-demo` | AppServicesStack | Public ALB | 80/tcp any, 443/tcp any | All |
| `lex-agents-dev-api-fargate` | AppServicesStack | API ECS tasks | 8000/tcp from ALB | All |
| `lex-agents-dev-web-fargate` | AppServicesStack | Web ECS tasks | 3000/tcp from ALB | All |
| `lex-agents-dev-qdrant` | AppServicesStack | Qdrant internal | 6333/tcp from API, 6334/tcp from API | 443/tcp, 2049/tcp EFS |
| `lex-agents-dev-efs` | AppServicesStack | EFS mount targets | 2049/tcp from ECS tasks, Qdrant | None |
| `lex-agents-dev-aurora-data` | DataStack | Aurora cluster (data layer) | 5432/tcp from API, rotation Lambda | None |
| `lex-agents-dev-aurora` (network) | NetworkSpokeStack | Aurora cluster (network layer) | 5432/tcp ECS API egress | None |
| `langfuse-dev-aurora` | LangfuseStack | Langfuse Aurora | 5432/tcp from Langfuse ECS | None |
| `langfuse-dev-ecs` | LangfuseStack | Langfuse ECS tasks | 3000/tcp from Langfuse ALB | 5432/tcp Aurora, 443/tcp |
| `langfuse-dev-alb` | LangfuseStack | Langfuse internal ALB | 443/tcp VPC CIDR | 3000/tcp ECS |
| `lex-agents-dev-alert-router` | ObservabilityStack | Alert router Lambda | None | 443/tcp Slack webhook |

---

## Service Control Policies (SCPs)

Applied at Organization Unit level via `OrganizationsStack`:

| SCP Name | Effect | Scope |
|----------|--------|-------|
| `DenyNonEuRegions` | DENY all actions outside eu-west-1, eu-central-1, us-east-1 | All workload OUs |
| `DenyRootUsage` | DENY all actions by root user | All OUs |
| `DenyUnencryptedStorage` | DENY S3 PutObject without SSE, RDS create without encryption | Workloads OU |
| `DenyIAMConsolePasswordWithoutMFA` | DENY console sign-in without MFA token present | All OUs |

---

## GuardDuty

| Setting | Value |
|---------|-------|
| Detector | Enabled, `SIX_HOURS` publishing frequency |
| S3 protection | Enabled |
| Malware protection | EC2 EBS scan on findings |
| Admin account | security account (333...) |
| Finding routing | EventBridge → SNS `lex-agents-security-alerts` |
| HIGH/CRITICAL threshold | Severity >= 7.0 |

---

## AWS Config

| Setting | Value |
|---------|-------|
| Recorder | All resources, all regions |
| Delivery channel | S3 + SNS |
| Conformance packs | AWS Operational Best Practices, CIS AWS Foundations |
| Compliance target | >= 80% rules compliant (monitored by `evidence_collector`) |
| Custom rules | None (Fase 9.5) — planned for Fase 10 |

---

## IAM Identity Center

| Permission Set | Level | Assigned Groups |
|---------------|-------|----------------|
| `AdministratorAccess` | Full admin | `lex-agents-admins` |
| `PowerUserAccess` | No IAM admin | `lex-agents-developers` |
| `ReadOnlyAccess` | Read only | `lex-agents-readonly` |
| `BillingAccess` | Cost Explorer + Billing | `lex-agents-finops` |

MFA policy: Required for all users at every session.
Session duration: 8h (admins), 8h (developers).

---

## VPC Architecture

| Account | VPC CIDR | Public Subnets | Private-App | Private-Data |
|---------|----------|---------------|-------------|--------------|
| workloads-dev | 10.10.0.0/16 | /24 x3 (eu-west-1a/b/c) | /24 x3 | /24 x3 |
| workloads-pre | 10.11.0.0/16 | /24 x3 (eu-central-1a/b/c) | /24 x3 | /24 x3 |
| network-hub | 10.20.0.0/16 | — | — | — |

VPC Endpoints (dev):
- S3 Gateway (free, all traffic stays in AWS network)
- Secrets Manager Interface (planned Fase 10)
- ECR API / ECR DKR Interface (planned Fase 10)

---

## Secrets Manager

| Secret Path | Purpose | Rotation |
|-------------|---------|---------|
| `/lex-agents/dev/db/master` | Aurora master credentials | 30d (Lambda rotator) |
| `/lex-agents/dev/db/app-user` | Aurora app-user | 30d (Lambda rotator, ADR 0050) |
| `/lex-agents/dev/anthropic/api-key` | Anthropic API key | Manual |
| `/lex-agents/dev/langfuse/secret-key` | Langfuse secret key | Manual |
| `/lex-agents/dev/langfuse/public-key` | Langfuse public key | Manual |
| `/lex-agents/dev/jwt/signing-key` | JWT signing key | Manual |
| `/lex-agents/dev/slack/webhook-url` | Slack alert webhook | Manual |
| `/lex-agents/dev/langfuse/nextauth-secret` | Langfuse NextAuth | Manual |

All secrets are encrypted with `lex-agents-dev-secrets` CMK.

---

## CloudTrail

| Setting | Value |
|---------|-------|
| Trail name | `lex-agents-org-trail` |
| Scope | Organization trail (all accounts) |
| Multi-region | Yes |
| Log file validation | Enabled |
| S3 bucket | `org-trail-logs-ACCOUNT` in log-archive account |
| Object Lock | COMPLIANCE mode, 7 years (2555 days) |
| Glacier transition | 7 days (lifecycle rule, cost optimization) |
| KMS encryption | `lex-agents-logarchive-logs` CMK |
| CloudWatch Logs | `/aws/cloudtrail/org-trail` (1 year retention) |

---

## Audit Manager (DORA)

| Setting | Value |
|---------|-------|
| Framework | Custom DORA-Banking (created via console) |
| Assessment | DORA-Banking-Quarterly |
| Assessment reports | `lex-agents-audit-reports-ACCOUNT` S3 bucket |
| Assessor role | `lex-agents-audit-manager-assessor-security` |
| Scope | All services in security account |
| Status | ACTIVE (when `lexAgents:doraFrameworkId` set in context) |

---

## Security Hub Custom Insights (DORA)

| Insight | Filter | Group By |
|---------|--------|---------|
| DORA-Encryption-Coverage | ComplianceStatus != PASSED AND title contains "encryption" | ResourceType |
| DORA-MFA-Coverage | ComplianceStatus != PASSED AND title contains "MFA" | AwsAccountId |
| DORA-Network-Segmentation | ComplianceStatus != PASSED AND title contains "security group" | ResourceId |

---

## WAF

Not deployed in Fase 9. Planned for Fase 10 when CloudFront distribution is added.
The ALB is internet-facing (HTTP/HTTPS) with default AWS DDoS protection (Shield Standard).
