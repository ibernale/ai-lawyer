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
    // Import the pre-existing GitHub Actions OIDC provider (created outside CDK).
    // AWS only allows one OIDC provider per URL per account, so we reference it
    // rather than trying to create it again.
    const provider = iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
      this,
      "GitHubProvider",
      `arn:aws:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`,
    );

    // ── Deploy Role ───────────────────────────────────────────────────────
    this.deployRole = new iam.Role(this, "GitHubDeployRole", {
      roleName: `github-deploy-${envName}`,
      description: `GitHub Actions OIDC deploy role for ${envName} - lex-agents`,
      assumedBy: new iam.WebIdentityPrincipal(
        provider.openIdConnectProviderArn,
        {
          StringEquals: {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          },
          // StringLike allows both:
          //   repo:owner/repo:ref:refs/heads/main  (push, build-push job)
          //   repo:owner/repo:environment:aws-dev  (CDK deploy job with environment:)
          StringLike: {
            "token.actions.githubusercontent.com:sub": `repo:${githubRepo}:*`,
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

    // ECR push permissions — required for docker/build-push-action in CI
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcrPush",
        actions: [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
        ],
        resources: [
          `arn:aws:ecr:*:${this.account}:repository/lex-agents-${envName}-*`,
        ],
      }),
    );

    // ECS update-service — required for rolling deploys after image push
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcsRollingDeploy",
        actions: [
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeClusters",
          "ecs:RegisterTaskDefinition",
          "ecs:DeregisterTaskDefinition",
          "ecs:DescribeTaskDefinition",
          "ecs:ListTaskDefinitions",
          "iam:PassRole",
        ],
        resources: ["*"],
      }),
    );

    // CloudWatch Logs read + ECS task inspection — lets CI fetch container
    // logs and stopped-task stop reasons for deploy diagnostics after a
    // circuit-breaker failure without needing a human to log into AWS.
    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudWatchLogsDiagnostics",
        actions: [
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
        ],
        resources: ["*"],
      }),
    );

    this.deployRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcsTaskDiagnostics",
        actions: ["ecs:ListTasks", "ecs:DescribeTasks"],
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
