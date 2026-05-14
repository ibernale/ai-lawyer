#!/usr/bin/env bash
set -euo pipefail

echo "=============================================="
echo " lex-agents IAM Identity Center bootstrap"
echo "=============================================="
echo ""
echo "This script prints the steps to create the first admin user."
echo "AWS CLI with Organizations permissions required."
echo ""

INSTANCE_ARN=$(aws sso-admin list-instances \
  --query 'Instances[0].InstanceArn' \
  --output text 2>/dev/null || echo "NOT_FOUND")

if [[ "$INSTANCE_ARN" == "NOT_FOUND" ]]; then
  echo "ERROR: IAM Identity Center not enabled or no permissions."
  echo "Enable Identity Center in management account first."
  exit 1
fi

echo "Identity Center instance ARN: $INSTANCE_ARN"
echo ""
echo "Steps to create first admin user:"
echo ""
echo "1. Open the Identity Center console:"
echo "   https://eu-central-1.console.aws.amazon.com/singlesignon/home"
echo ""
echo "2. Go to Users -> Add user"
echo "   Email: your-admin@yourdomain.com"
echo "   Group: add to 'admins' group (create if needed)"
echo ""
echo "3. Assign permission set to user:"
echo "   Account assignments -> Select management account"
echo "   Permission set: AdministratorAccess"
echo ""
echo "4. User receives email invitation -- accept and set up MFA (WebAuthn)"
echo ""
echo "5. Add instance ARN to cdk.context.json:"
echo "   \"lexAgents:identityCenterInstanceArn\": \"$INSTANCE_ARN\""
echo ""
echo "Done. Run 'cdk deploy LexAgents-IdentityCenter' to create permission sets."
