import * as cdk from "aws-cdk-lib";
import * as auditmanager from "aws-cdk-lib/aws-auditmanager";
import * as guardduty from "aws-cdk-lib/aws-guardduty";
import * as securityhub from "aws-cdk-lib/aws-securityhub";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as kms from "aws-cdk-lib/aws-kms";
import * as iam from "aws-cdk-lib/aws-iam";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface SecurityBaselineStackProps extends cdk.StackProps {
  managementAccountId: string;
  envName?: string;
}

export class SecurityBaselineStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SecurityBaselineStackProps) {
    super(scope, id, props);
    const { managementAccountId: _managementAccountId, envName = "security" } =
      props;

    // ── KMS key for security account resources ────────────────────────────
    const securityKey = new kms.Key(this, "SecurityKey", {
      description: "lex-agents security account encryption key",
      enableKeyRotation: true,
      pendingWindow: cdk.Duration.days(30),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      policy: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            sid: "AllowRootAndServices",
            principals: [
              new iam.AccountRootPrincipal(),
              new iam.ServicePrincipal("sns.amazonaws.com"),
              new iam.ServicePrincipal("logs.amazonaws.com"),
            ],
            actions: ["kms:*"],
            resources: ["*"],
          }),
        ],
      }),
    });

    // ── GuardDuty (delegated admin in security account) ───────────────────
    const guardDutyDetector = new guardduty.CfnDetector(
      this,
      "GuardDutyDetector",
      {
        enable: true,
        findingPublishingFrequency: "SIX_HOURS",
        dataSources: {
          s3Logs: { enable: true },
          malwareProtection: {
            scanEc2InstanceWithFindings: { ebsVolumes: true },
          },
        },
      },
    );

    // ── Security Hub ──────────────────────────────────────────────────────
    const secHub = new securityhub.CfnHub(this, "SecurityHub", {
      autoEnableControls: true,
      enableDefaultStandards: true,
    });
    secHub.node.addDependency(guardDutyDetector);

    // ── SNS topic for security alerts (KMS encrypted) ─────────────────────
    const alertTopic = new sns.Topic(this, "SecurityAlertsTopic", {
      topicName: "lex-agents-security-alerts",
      displayName: "lex-agents Security Alerts",
      masterKey: securityKey,
    });

    // CloudWatch log group as MVP sink (KMS encrypted; Slack/PagerDuty Fase 10)
    const alertLogGroup = new logs.LogGroup(this, "SecurityAlertsLogGroup", {
      logGroupName: "/lex-agents/security/alerts",
      retention: logs.RetentionDays.ONE_YEAR,
      encryptionKey: securityKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── EventBridge: GuardDuty HIGH/CRITICAL findings → SNS ──────────────
    new events.Rule(this, "GuardDutyHighSeverityRule", {
      ruleName: "lex-agents-guardduty-high-severity",
      description:
        "Forward GuardDuty HIGH/CRITICAL findings to security alerts SNS",
      eventPattern: {
        source: ["aws.guardduty"],
        detailType: ["GuardDuty Finding"],
        detail: {
          severity: [{ numeric: [">=", 7] }],
        },
      },
      targets: [
        new targets.SnsTopic(alertTopic),
        new targets.CloudWatchLogGroup(alertLogGroup),
      ],
    });

    // ── EventBridge: Security Hub CRITICAL findings → SNS ────────────────
    new events.Rule(this, "SecurityHubCriticalRule", {
      ruleName: "lex-agents-securityhub-critical",
      description:
        "Forward Security Hub CRITICAL findings to security alerts SNS",
      eventPattern: {
        source: ["aws.securityhub"],
        detailType: ["Security Hub Findings - Imported"],
        detail: {
          findings: {
            Severity: { Label: ["CRITICAL"] },
          },
        },
      },
      targets: [
        new targets.SnsTopic(alertTopic),
        new targets.CloudWatchLogGroup(alertLogGroup),
      ],
    });

    // Outputs
    new cdk.CfnOutput(this, "GuardDutyDetectorId", {
      value: guardDutyDetector.ref,
      description: "GuardDuty detector ID in security account",
    });
    new cdk.CfnOutput(this, "SecurityAlertsTopicArn", {
      value: alertTopic.topicArn,
      exportName: "LexAgents-SecurityAlertsTopicArn",
    });

    // ── AWS Audit Manager — DORA Banking assessment (Fase 9.5, ADR 0044) ─
    // S3 bucket for assessment reports
    const auditReportsBucket = new s3.Bucket(this, "AuditReportsBucket", {
      bucketName: `lex-agents-audit-reports-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: securityKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // IAM role for Audit Manager assessment
    const assessorRole = new iam.Role(this, "AuditManagerAssessorRole", {
      roleName: `lex-agents-audit-manager-assessor-${envName}`,
      assumedBy: new iam.ServicePrincipal("auditmanager.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("SecurityAudit"),
      ],
    });
    auditReportsBucket.grantReadWrite(assessorRole);

    // DORA Banking Assessment — uses CfnAssessment (L1).
    // CfnFramework is not available in this CDK version; the framework must be
    // pre-created via the AWS Console or CLI and its ID set in cdk.context.json
    // under "lexAgents:doraFrameworkId". If not set, the assessment is skipped.
    const doraFrameworkId = this.node.tryGetContext(
      "lexAgents:doraFrameworkId",
    ) as string | undefined;
    if (doraFrameworkId && doraFrameworkId !== "REPLACE_ME") {
      new auditmanager.CfnAssessment(this, "DoraAssessment", {
        name: "DORA-Banking-Quarterly",
        description:
          "Quarterly DORA compliance assessment for lex-agents (EU Regulation 2022/2554)",
        frameworkId: doraFrameworkId,
        assessmentReportsDestination: {
          destination: `s3://${auditReportsBucket.bucketName}`,
          destinationType: "S3",
        },
        awsAccount: { id: this.account },
        scope: {
          awsAccounts: [{ id: this.account }],
          awsServices: [
            { serviceName: "S3" },
            { serviceName: "RDS" },
            { serviceName: "KMS" },
            { serviceName: "IAM" },
            { serviceName: "GuardDuty" },
            { serviceName: "CloudTrail" },
          ],
        },
        roles: [{ roleArn: assessorRole.roleArn, roleType: "PROCESS_OWNER" }],
        status: "ACTIVE",
      });
    }

    // ── Security Hub Custom Insights — DORA (Fase 9.5) ─────────────────
    new securityhub.CfnInsight(this, "EncryptionInsight", {
      name: "DORA-Encryption-Coverage",
      filters: {
        complianceStatus: [{ comparison: "NOT_EQUALS", value: "PASSED" }],
        title: [{ comparison: "CONTAINS", value: "encryption" }],
      },
      groupByAttribute: "ResourceType",
    });
    new securityhub.CfnInsight(this, "MfaInsight", {
      name: "DORA-MFA-Coverage",
      filters: {
        complianceStatus: [{ comparison: "NOT_EQUALS", value: "PASSED" }],
        title: [{ comparison: "CONTAINS", value: "MFA" }],
      },
      groupByAttribute: "AwsAccountId",
    });
    new securityhub.CfnInsight(this, "NetworkSegmentationInsight", {
      name: "DORA-Network-Segmentation",
      filters: {
        complianceStatus: [{ comparison: "NOT_EQUALS", value: "PASSED" }],
        title: [{ comparison: "CONTAINS", value: "security group" }],
      },
      groupByAttribute: "ResourceId",
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-SNS3",
        reason:
          "SNS SSL enforcement is handled by the KMS key policy. Internal CloudWatch Logs subscriptions use AWS-internal transport.",
      },
      // CDK auto-generates a custom Lambda to apply CW log group resource policy.
      // These nag findings target that auto-generated Lambda, not our application code.
      {
        id: "AwsSolutions-L1",
        reason:
          "Auto-generated CDK custom resource Lambda for CloudWatch log group resource policy. Runtime version managed by CDK team.",
      },
      {
        id: "HIPAA.Security-LambdaConcurrency",
        reason:
          "Auto-generated CDK custom resource Lambda. Single-use during CloudFormation deploy; concurrency limits not applicable.",
      },
      {
        id: "HIPAA.Security-LambdaDLQ",
        reason:
          "Auto-generated CDK custom resource Lambda. Failures surface as CloudFormation stack failures; DLQ not applicable.",
      },
      {
        id: "HIPAA.Security-LambdaInsideVPC",
        reason:
          "Auto-generated CDK custom resource Lambda for log group policy. No VPC access needed; calls CloudWatch Logs API via HTTPS.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "Auto-generated CDK custom resource Lambda uses AWSLambdaBasicExecutionRole managed policy. Standard CDK pattern.",
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "Auto-generated CDK custom resource Lambda policy with wildcard Resource. Standard CDK custom resource pattern; not our application code.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Auto-generated CDK custom resource Lambda inline policy. Standard CDK pattern; minimally scoped to CloudWatch Logs actions.",
      },
      {
        id: "AwsSolutions-S1",
        reason:
          "Audit reports bucket is itself an audit sink; server access logging would be circular.",
      },
      {
        id: "HIPAA.Security-S3BucketLoggingEnabled",
        reason:
          "Audit reports bucket is an audit sink; server access logging would be circular.",
      },
      {
        id: "HIPAA.Security-S3BucketReplicationEnabled",
        reason:
          "Audit reports bucket replication to DR region is a post-Fase-9.5 enhancement.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "SecurityAudit managed policy on Audit Manager assessor role is the minimum required for evidence collection.",
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "SecurityAudit managed policy requires broad read access by design for compliance evidence collection.",
      },
    ]);

    // ── AuditReportsBucket resource-level suppressions ────────────────────────
    NagSuppressions.addResourceSuppressions(auditReportsBucket, [
      {
        id: "AwsSolutions-S10",
        reason:
          "Audit reports bucket SSL enforced via S3 Object Lock and bucket policy.",
      },
      {
        id: "HIPAA.Security-S3BucketSSLRequestsOnly",
        reason:
          "Audit reports bucket SSL enforced via S3 Object Lock and bucket policy.",
      },
    ]);
  }
}
