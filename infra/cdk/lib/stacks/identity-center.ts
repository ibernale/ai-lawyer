import * as cdk from "aws-cdk-lib";
import * as sso from "aws-cdk-lib/aws-sso";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export class IdentityCenterStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    // IAM Identity Center instance ARN must be retrieved at deploy time via AWS CLI.
    // CDK cannot create the IC instance (it's auto-created by AWS when IC is enabled).
    // Provide via context: lexAgents:identityCenterInstanceArn
    const instanceArn =
      this.node.tryGetContext("lexAgents:identityCenterInstanceArn") ??
      "PLACEHOLDER_IDENTITY_CENTER_INSTANCE_ARN";

    // ── Permission Sets ───────────────────────────────────────────────────
    const administratorPS = new sso.CfnPermissionSet(
      this,
      "AdministratorAccessPS",
      {
        instanceArn,
        name: "AdministratorAccess",
        description:
          "Full administrator access. MFA + email approval required.",
        managedPolicies: ["arn:aws:iam::aws:policy/AdministratorAccess"],
        sessionDuration: "PT4H",
      },
    );

    const developerPS = new sso.CfnPermissionSet(this, "DeveloperAccessPS", {
      instanceArn,
      name: "DeveloperAccess",
      description: "Power user access for workloads-dev account.",
      managedPolicies: ["arn:aws:iam::aws:policy/PowerUserAccess"],
      sessionDuration: "PT8H",
    });

    const dataAnalystPS = new sso.CfnPermissionSet(
      this,
      "DataAnalystAccessPS",
      {
        instanceArn,
        name: "DataAnalystAccess",
        description: "Read-only access plus Athena for log analysis.",
        managedPolicies: [
          "arn:aws:iam::aws:policy/ReadOnlyAccess",
          "arn:aws:iam::aws:policy/AmazonAthenaFullAccess",
        ],
        sessionDuration: "PT8H",
      },
    );

    const securityAuditPS = new sso.CfnPermissionSet(
      this,
      "SecurityAuditAccessPS",
      {
        instanceArn,
        name: "SecurityAuditAccess",
        description: "Security audit read-only across all accounts.",
        managedPolicies: ["arn:aws:iam::aws:policy/SecurityAudit"],
        sessionDuration: "PT8H",
      },
    );

    // Outputs (groups and assignments are created manually in IC console
    // after bootstrapping the first admin user — see docs/aws/account-bootstrap.md)
    new cdk.CfnOutput(this, "AdministratorPSArn", {
      value: administratorPS.attrPermissionSetArn,
      description: "AdministratorAccess permission set ARN",
    });
    new cdk.CfnOutput(this, "DeveloperPSArn", {
      value: developerPS.attrPermissionSetArn,
      description: "DeveloperAccess permission set ARN",
    });
    new cdk.CfnOutput(this, "DataAnalystPSArn", {
      value: dataAnalystPS.attrPermissionSetArn,
      description: "DataAnalystAccess permission set ARN",
    });
    new cdk.CfnOutput(this, "SecurityAuditPSArn", {
      value: securityAuditPS.attrPermissionSetArn,
      description: "SecurityAuditAccess permission set ARN",
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM4",
        reason:
          "SSO permission sets use AWS managed policies by design; custom inline policies are additive but the managed policies are required for the permission sets to function.",
      },
    ]);
  }
}
