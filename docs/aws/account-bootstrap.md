# AWS Account Bootstrap

Step-by-step guide to bring the lex-agents AWS foundation from zero to a working CDK deployment. Requires access to the Santander AWS management account.

---

## Prerequisites

- AWS CLI v2 installed and configured with management account credentials
- Node 20+ and pnpm 9+ installed
- CDK dependencies installed: `make cdk-install`

---

## Step 1 — AWS Organizations + Control Tower

1. Log into the management account AWS Console as root (one-time only).
2. Navigate to **AWS Organizations** and create the organization (if not done).
3. Navigate to **AWS Control Tower** and launch the landing zone.
   - Home region: `eu-central-1`
   - Log archive account: create a new account named `lex-agents-log-archive`
   - Audit account: create a new account named `lex-agents-security`
   - Enable all recommended guardrails.
4. Wait for Control Tower setup to complete (15-30 minutes).

---

## Step 2 — Create remaining accounts via Account Factory

In Control Tower, go to **Account Factory → Enroll account** for each:

| Account name             | Email                      | OU             |
| ------------------------ | -------------------------- | -------------- |
| lex-agents-network       | aws+network@yourdomain.com | Infrastructure |
| lex-agents-workloads-dev | aws+dev@yourdomain.com     | Workloads      |
| lex-agents-workloads-pre | aws+pre@yourdomain.com     | Workloads      |

Wait for all accounts to be provisioned (5-10 minutes each).

---

## Step 3 — Enable IAM Identity Center

1. In the management account console, navigate to **IAM Identity Center**.
2. Click **Enable**. AWS creates the instance automatically (cannot be done via CDK).
3. Note the instance ARN — you will need it in Step 5.
   ```bash
   aws sso-admin list-instances \
     --query 'Instances[0].InstanceArn' \
     --output text
   ```

---

## Step 4 — Get all account IDs

```bash
aws organizations list-accounts \
  --query 'Accounts[*].[Name,Id]' \
  --output table
```

Note the account ID for each of the five accounts.

---

## Step 5 — Fill in cdk.context.json

```bash
cd infra/cdk
cp cdk.context.json.example cdk.context.json
```

Edit `cdk.context.json` and replace the placeholder values:

```json
{
  "lexAgents:accounts": {
    "management": "REAL_MANAGEMENT_ACCOUNT_ID",
    "logArchive": "REAL_LOG_ARCHIVE_ACCOUNT_ID",
    "security": "REAL_SECURITY_ACCOUNT_ID",
    "network": "REAL_NETWORK_ACCOUNT_ID",
    "workloadsDev": "REAL_WORKLOADS_DEV_ACCOUNT_ID"
  },
  "lexAgents:rootOuId": "r-XXXX",
  "lexAgents:identityCenterInstanceArn": "arn:aws:sso:::instance/ssoins-XXXXXXXXXXXXXXXX"
}
```

To get the root OU ID:

```bash
aws organizations list-roots --query 'Roots[0].Id' --output text
```

**IMPORTANT: Never commit `cdk.context.json` — it contains account IDs. It is in `.gitignore`.**

---

## Step 6 — Bootstrap CDK in each account

CDK bootstrap must be run once per account/region before the first deploy. Run from the management account with cross-account permissions (Control Tower gives this via AWSControlTowerExecution role):

```bash
# Management account
cdk bootstrap aws://MANAGEMENT_ACCOUNT_ID/eu-central-1

# Log archive
cdk bootstrap aws://LOG_ARCHIVE_ACCOUNT_ID/eu-central-1 \
  --trust MANAGEMENT_ACCOUNT_ID \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess

# Security
cdk bootstrap aws://SECURITY_ACCOUNT_ID/eu-central-1 \
  --trust MANAGEMENT_ACCOUNT_ID \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess

# Network
cdk bootstrap aws://NETWORK_ACCOUNT_ID/eu-central-1 \
  --trust MANAGEMENT_ACCOUNT_ID \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess

# Workloads-dev
cdk bootstrap aws://WORKLOADS_DEV_ACCOUNT_ID/eu-central-1 \
  --trust MANAGEMENT_ACCOUNT_ID \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess
```

---

## Step 7 — Deploy stacks in order

```bash
# Validate first (no AWS calls)
make cdk-synth

# Deploy management stacks
cd infra/cdk
npx cdk deploy LexAgents-Organizations LexAgents-IdentityCenter

# Deploy log-archive stacks (parallel-safe)
npx cdk deploy LexAgents-LogArchive-Kms
npx cdk deploy LexAgents-LogArchive

# Deploy security stack
npx cdk deploy LexAgents-SecurityBaseline

# Deploy network hub stack
npx cdk deploy LexAgents-NetworkHub

# Deploy workloads-dev stacks
make cdk-deploy-dev
```

---

## Step 8 — Bootstrap IAM Identity Center admin user

```bash
make idc-bootstrap
```

This prints step-by-step instructions for creating the first admin user via the IAM Identity Center console and assigning them the AdministratorAccess permission set.

---

## Troubleshooting

**`Missing CDK context "lexAgents:accounts"`** — `cdk.context.json` not present. Run `cp cdk.context.json.example cdk.context.json` and fill in real account IDs.

**`BUCKET_NOT_FOUND` during deploy** — CDK bootstrap not run in that account. Run Step 6 for the affected account.

**`Organizations policy type not enabled`** — Enable SCP policy type in Organizations before deploying the Organizations stack:

```bash
aws organizations enable-policy-type \
  --root-id r-XXXX \
  --policy-type SERVICE_CONTROL_POLICY
```
