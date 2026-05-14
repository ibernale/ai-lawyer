# AWS Foundation — Fase 9.1

Multi-account AWS foundation for lex-agents. Implements DORA-compliant data residency (EU only), strong separation of concerns via AWS Organizations OUs, centralised audit trail, and GitHub Actions OIDC for keyless deployments.

---

## Account structure

Five dedicated accounts under AWS Organizations, grouped into three OUs:

```mermaid
graph TD
    ROOT[AWS Organizations Root]

    ROOT --> SECURITY_OU[Security OU]
    ROOT --> INFRA_OU[Infrastructure OU]
    ROOT --> WORKLOADS_OU[Workloads OU]

    SECURITY_OU --> SEC_ACCOUNT[security\nGuardDuty delegated admin\nSecurity Hub aggregator]
    INFRA_OU --> LOG_ACCOUNT[log-archive\nOrg CloudTrail S3 WORM\nAthena audit queries]
    INFRA_OU --> NET_ACCOUNT[network\nTransit Gateway hub\nRoute53 Resolver]
    WORKLOADS_OU --> DEV_ACCOUNT[workloads-dev\nECS / Aurora / Qdrant\nGitHub OIDC deploy]
    WORKLOADS_OU --> PRE_ACCOUNT[workloads-pre\nFase 9.3 placeholder]

    MGMT[management\nOrganizations + Control Tower\nIAM Identity Center]
    ROOT --- MGMT
```

Service Control Policies applied at OU level:

| SCP                        | Applied to OUs                      | Purpose                                               |
| -------------------------- | ----------------------------------- | ----------------------------------------------------- |
| DenyNonEuRegions           | Security, Infrastructure, Workloads | DORA data residency — only eu-central-1 and eu-west-1 |
| DenyRootUsage              | Workloads                           | Prevent root account use without MFA                  |
| DenyUnencryptedStorage     | Workloads                           | Force SSE-KMS on S3 PutObject; deny unencrypted EBS   |
| RequireMFASensitiveActions | Workloads                           | MFA required for IAM/KMS/Org destructive operations   |

---

## Stacks

| Stack name                 | Target account | Purpose                                                            |
| -------------------------- | -------------- | ------------------------------------------------------------------ |
| LexAgents-Organizations    | management     | OUs + 4 SCPs + policy attachments                                  |
| LexAgents-IdentityCenter   | management     | SSO permission sets (Admin, Developer, DataAnalyst, SecurityAudit) |
| LexAgents-LogArchive-Kms   | log-archive    | KMS logs key (CloudTrail, VPC flow logs)                           |
| LexAgents-LogArchive       | log-archive    | Org CloudTrail S3 WORM bucket, Athena workgroup, CW log group      |
| LexAgents-SecurityBaseline | security       | GuardDuty detector, Security Hub, SNS alerts, EventBridge rules    |
| LexAgents-NetworkHub       | network        | Transit Gateway, hub VPC, VPC endpoints, Route53 Resolver inbound  |
| LexAgents-Dev-Kms          | workloads-dev  | KMS keys: logs + rds + s3 + secrets + ebs                          |
| LexAgents-Dev-Network      | workloads-dev  | Spoke VPC (3 AZ × 3 tier), SGs, NACLs, VPC flow logs               |
| LexAgents-Dev-GithubOidc   | workloads-dev  | OIDC provider + scoped deploy role for GitHub Actions              |

---

## Stack deployment order

Dependencies flow top-to-bottom. Stacks on the same level can deploy in parallel.

```
1. LexAgents-Organizations          (management — no dependencies)
2. LexAgents-IdentityCenter         (management — no dependencies)
   LexAgents-LogArchive-Kms         (log-archive — no dependencies)
   LexAgents-SecurityBaseline       (security — no dependencies)
   LexAgents-NetworkHub             (network — no dependencies)
   LexAgents-Dev-Kms                (workloads-dev — no dependencies)
3. LexAgents-LogArchive             (log-archive — needs LogArchive-Kms)
   LexAgents-Dev-Network            (workloads-dev — needs Dev-Kms at runtime, standalone at synth)
   LexAgents-Dev-GithubOidc         (workloads-dev — no stack dependencies)
```

Bootstrap each account before first deploy:

```bash
cdk bootstrap aws://ACCOUNT_ID/eu-central-1 --trust MANAGEMENT_ACCOUNT_ID
```

---

## VPC topology (workloads-dev)

Three availability zones, three subnet tiers, three NAT gateways (one per AZ for HA).

```mermaid
graph LR
    subgraph eu-central-1a
        PUB_A[public\n10.10.0.0/24]
        APP_A[private-app\n10.10.10.0/24]
        DATA_A[private-data\n10.10.20.0/24]
    end
    subgraph eu-central-1b
        PUB_B[public\n10.10.1.0/24]
        APP_B[private-app\n10.10.11.0/24]
        DATA_B[private-data\n10.10.21.0/24]
    end
    subgraph eu-central-1c
        PUB_C[public\n10.10.2.0/24]
        APP_C[private-app\n10.10.12.0/24]
        DATA_C[private-data\n10.10.22.0/24]
    end

    IGW[Internet Gateway] --> PUB_A & PUB_B & PUB_C
    PUB_A --> NGW_A[NAT GW A]
    PUB_B --> NGW_B[NAT GW B]
    PUB_C --> NGW_C[NAT GW C]
    NGW_A --> APP_A
    NGW_B --> APP_B
    NGW_C --> APP_C
    APP_A & APP_B & APP_C --> DATA_A & DATA_B & DATA_C

    APP_A & APP_B & APP_C --> VPCE[VPC Endpoints\nBedrock / ECR / KMS\nSecrets / SSM / CW]
```

Security group hierarchy:

```
CloudFront (prefix list) → sgAlb (443)
                         → sgEcsWeb (3000) → sgEcsApi (8000)
                                           → sgAurora (5432)
sgAgentcore (egress only) → sgAurora (5432)
                          → VPCE (443)
```

Private-data subnets are additionally protected by a NACL that allows only PostgreSQL (5432) ingress from private-app CIDRs and denies everything else.
