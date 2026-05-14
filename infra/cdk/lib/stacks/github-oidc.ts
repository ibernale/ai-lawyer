import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface GithubOidcStackProps extends cdk.StackProps {
  envName: string;
  githubRepo: string; // e.g. "ibernale/ai-lawyer"
  githubBranch: string; // e.g. "main"
}

export class GithubOidcStack extends cdk.Stack {
  public readonly deployRole: iam.Role;

  constructor(scope: Construct, id: string, props: GithubOidcStackProps) {
    super(scope, id, props);
    const { envName, githubRepo, githubBranch } = props;

    // ── OIDC Provider ─────────────────────────────────────────────────────
    const provider = new iam.OpenIdConnectProvider(this, "GitHubProvider", {
      url: "https://token.actions.githubusercontent.com",
      clientIds: ["sts.amazonaws.com"],
      thumbprints: ["6938fd4d98bab03faadb97b34396831e3780aea1"],
    });

    // ── Deploy Role ───────────────────────────────────────────────────────
    this.deployRole = new iam.Role(this, "GitHubDeployRole", {
      roleName: `github-deploy-${envName}`,
      description: `GitHub Actions OIDC deploy role for ${envName} - lex-agents`,
      assumedBy: new iam.WebIdentityPrincipal(
        provider.openIdConnectProviderArn,
        {
          StringEquals: {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": `repo:${githubRepo}:ref:refs/heads/${githubBranch}`,
          },
        },
      ),
      maxSessionDuration: cdk.Duration.hours(1),
    });

    // Scoped permissions: CloudFormation + CDK bootstrap + ECR (Fase 9.2 prep)
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudFormationDeploy",
        actions: [
          "cloudformation:CreateStack",
          "cloudformation:UpdateStack",
          "cloudformation:DeleteStack",
          "cloudformation:DescribeStacks",
          "cloudformation:DescribeStackEvents",
          "cloudformation:GetTemplate",
          "cloudformation:ValidateTemplate",
          "cloudformation:CreateChangeSet",
          "cloudformation:ExecuteChangeSet",
          "cloudformation:DescribeChangeSet",
        ],
        resources: ["*"],
      }),
    );

    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CDKBootstrapAccess",
        actions: [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "ssm:GetParameter",
          "ecr:GetAuthorizationToken",
          "sts:AssumeRole",
        ],
        resources: ["*"],
      }),
    );

    new cdk.CfnOutput(this, "DeployRoleArn", {
      value: this.deployRole.roleArn,
      exportName: `LexAgents-${envName}-GitHubDeployRoleArn`,
      description: "Set as AWS_ROLE_ARN in GitHub Actions environment aws-dev",
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM5",
        reason:
          "CDK deploy role requires broad Resource: * for CloudFormation and CDK bootstrap bucket/SSM/ECR access. Standard CDK deployment pattern. Role is assumable ONLY from a specific repo+branch via OIDC StringEquals conditions.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "GitHub deploy role does not use AWS managed policies — only inline scoped action policies.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "GitHub deploy role uses inline policies scoped to specific CDK deployment actions. Inline policy provides tighter coupling between the role and its permissions than a standalone managed policy.",
      },
    ]);
  }
}
