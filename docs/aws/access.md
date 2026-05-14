# AWS Access Guide

How to access lex-agents AWS accounts using IAM Identity Center (SSO). All human access goes through SSO — no long-lived IAM user access keys.

---

## Portal URL

After IAM Identity Center is enabled, find the portal URL:

```bash
aws sso-admin list-instances \
  --query 'Instances[0].IdentityStoreId' \
  --output text
```

Or in the console: **IAM Identity Center → Dashboard → AWS access portal URL**

The URL format is: `https://d-XXXXXXXXXX.awsapps.com/start`

---

## Login steps

1. Open the portal URL in a browser.
2. Enter your corporate email address.
3. Complete MFA challenge — **WebAuthn (hardware key or Face ID) is required**. TOTP is allowed as a fallback for emergency access only.
4. You will see a list of accounts and permission sets you have been assigned.
5. Click the account and permission set to open the console, or copy temporary CLI credentials.

---

## Roles and permissions

| Role              | Permission Set      | What you can do                                                           |
| ----------------- | ------------------- | ------------------------------------------------------------------------- |
| Platform engineer | AdministratorAccess | Full access to all resources. Session: 4h. Requires MFA.                  |
| Developer         | DeveloperAccess     | PowerUser — all AWS services except IAM admin and billing. Session: 8h.   |
| Data analyst      | DataAnalystAccess   | Read-only across all services + full Athena for log queries. Session: 8h. |
| Security team     | SecurityAuditAccess | Read-only security audit across all accounts. Session: 8h.                |

Permission sets are managed via CDK in `LexAgents-IdentityCenter` stack. Group assignments are done manually in the Identity Center console (see `docs/aws/account-bootstrap.md`).

---

## AWS CLI with SSO

Configure a named profile for each account you need:

```bash
aws configure sso --profile lex-agents-dev
```

Follow the prompts:

- SSO start URL: `https://d-XXXXXXXXXX.awsapps.com/start`
- SSO region: `eu-central-1`
- Account ID: (workloads-dev account ID)
- Role: `DeveloperAccess`
- Default output format: `json`
- Default region: `eu-central-1`

Then use it:

```bash
aws s3 ls --profile lex-agents-dev
```

To login (opens browser):

```bash
aws sso login --profile lex-agents-dev
```

To set as default for the shell session:

```bash
export AWS_PROFILE=lex-agents-dev
```

---

## Suggested profiles

Add these to `~/.aws/config` after running `aws configure sso` for each:

```ini
[profile lex-agents-mgmt]
sso_start_url = https://d-XXXXXXXXXX.awsapps.com/start
sso_region = eu-central-1
sso_account_id = MANAGEMENT_ACCOUNT_ID
sso_role_name = AdministratorAccess
region = eu-central-1

[profile lex-agents-dev]
sso_start_url = https://d-XXXXXXXXXX.awsapps.com/start
sso_region = eu-central-1
sso_account_id = WORKLOADS_DEV_ACCOUNT_ID
sso_role_name = DeveloperAccess
region = eu-central-1

[profile lex-agents-security]
sso_start_url = https://d-XXXXXXXXXX.awsapps.com/start
sso_region = eu-central-1
sso_account_id = SECURITY_ACCOUNT_ID
sso_role_name = SecurityAuditAccess
region = eu-central-1
```

---

## Switching roles in the browser

In the AWS Console:

1. Click your account name (top right) → **Switch role**
2. Or use the IAM Identity Center portal to jump directly to an account/role combination
3. The console will prompt for MFA when accessing Administrator permission sets

---

## GitHub Actions (keyless OIDC)

CI/CD never uses long-lived credentials. The `LexAgents-Dev-GithubOidc` stack creates an OIDC provider and a scoped deploy role.

Set up in GitHub repository settings:

1. Go to **Settings → Environments → aws-dev**
2. Add variable `AWS_DEPLOY_ROLE_ARN` = value from `DeployRoleArn` CDK output
3. The CDK Deploy workflow will authenticate automatically via `aws-actions/configure-aws-credentials@v4`

Only pushes from `main` branch of `ibernale/ai-lawyer` can assume the deploy role (enforced by OIDC conditions in the role trust policy).
