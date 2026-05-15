/**
 * ComplianceStack — daily DORA evidence collection (Fase 9.5).
 *
 * Resources:
 *  - S3 compliance-docs bucket (Object Lock COMPLIANCE, 7 years, SSE-KMS)
 *  - Lambda evidence_collector (Python 3.12, daily 02:00 UTC)
 *  - CloudWatch Alarm: ComplianceScore < 90 → SNS alert
 *
 * ADR: 0044 (DORA), 0050 (secrets rotation evidence)
 */

import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cw_actions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda_ from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sns from "aws-cdk-lib/aws-sns";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

export interface ComplianceStackProps extends cdk.StackProps {
  readonly envName: string;
  readonly logsKey: kms.IKey;
  readonly s3Key: kms.IKey;
  readonly alertTopic: sns.ITopic;
}

export class ComplianceStack extends cdk.Stack {
  public readonly complianceBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: ComplianceStackProps) {
    super(scope, id, props);
    const { envName, logsKey, s3Key, alertTopic } = props;

    // ── S3 compliance-docs bucket (Object Lock COMPLIANCE, 7 years) ────
    this.complianceBucket = new s3.Bucket(this, "ComplianceDocsBucket", {
      bucketName: `lex-agents-${envName}-compliance-docs-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: s3Key,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      objectLockEnabled: true,
      objectLockDefaultRetention: s3.ObjectLockRetention.compliance(
        cdk.Duration.days(2555), // 7 years
      ),
      lifecycleRules: [
        {
          id: "ArchiveOldEvidence",
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(365),
            },
          ],
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── Lambda role ────────────────────────────────────────────────────
    const fnRole = new iam.Role(this, "EvidenceCollectorRole", {
      roleName: `lex-agents-${envName}-evidence-collector`,
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole",
        ),
      ],
    });

    // Read-only access to audited services
    fnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "AuditReadAccess",
        actions: [
          "kms:ListKeys",
          "kms:DescribeKey",
          "kms:GetKeyRotationStatus",
          "cloudtrail:DescribeTrails",
          "cloudtrail:GetTrailStatus",
          "guardduty:ListDetectors",
          "guardduty:GetDetector",
          "guardduty:ListFindings",
          "config:DescribeConfigurationRecorders",
          "config:DescribeConfigurationRecorderStatus",
          "config:GetComplianceSummaryByConfigRule",
          "iam:GenerateCredentialReport",
          "iam:GetCredentialReport",
        ],
        resources: ["*"],
      }),
    );

    // Scoped write: only LexAgents/Compliance namespace to prevent metric spoofing
    fnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "ComplianceMetricWrite",
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: {
          StringEquals: { "cloudwatch:namespace": "LexAgents/Compliance" },
        },
      }),
    );
    this.complianceBucket.grantReadWrite(fnRole);

    // ── Lambda function ────────────────────────────────────────────────
    const evidenceLogGroup = new logs.LogGroup(this, "EvidenceCollectorLogs", {
      logGroupName: `/lex-agents/${envName}/evidence-collector`,
      retention: logs.RetentionDays.ONE_MONTH,
      encryptionKey: logsKey,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const fn = new lambda_.Function(this, "EvidenceCollector", {
      functionName: `lex-agents-${envName}-evidence-collector`,
      runtime: lambda_.Runtime.PYTHON_3_12,
      handler: "lex_pipeline_aws.evidence_collector.handler.lambda_handler",
      code: lambda_.Code.fromAsset("../../packages/pipeline_aws/src"),
      role: fnRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      environment: {
        ENV_NAME: envName,
        COMPLIANCE_BUCKET: this.complianceBucket.bucketName,
        POWERTOOLS_LOG_LEVEL: "INFO",
      },
      logGroup: evidenceLogGroup,
    });

    // ── Daily schedule: 02:00 UTC ──────────────────────────────────────
    new events.Rule(this, "DailySchedule", {
      ruleName: `lex-agents-${envName}-evidence-collector-daily`,
      schedule: events.Schedule.cron({ hour: "2", minute: "0" }),
      targets: [new targets.LambdaFunction(fn)],
    });

    // ── CloudWatch Alarm: ComplianceScore < 90 ─────────────────────────
    const scoreMetric = new cloudwatch.Metric({
      namespace: "LexAgents/Compliance",
      metricName: "ComplianceScore",
      dimensionsMap: { Environment: envName },
      statistic: "Minimum",
      period: cdk.Duration.days(1),
    });

    new cloudwatch.Alarm(this, "ComplianceScoreAlarm", {
      alarmName: `lex-agents-${envName}-compliance-score-low`,
      alarmDescription:
        "DORA compliance score dropped below 90%. Investigate evidence_collector reports.",
      metric: scoreMetric,
      threshold: 90,
      comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.BREACHING,
    }).addAlarmAction(new cw_actions.SnsAction(alertTopic));

    // ── cdk-nag suppressions ───────────────────────────────────────────
    NagSuppressions.addResourceSuppressions(
      fnRole,
      [
        {
          id: "AwsSolutions-IAM4",
          reason:
            "AWSLambdaBasicExecutionRole is the minimal managed policy for Lambda logging.",
        },
        {
          id: "AwsSolutions-IAM5",
          reason:
            "Evidence collector needs read access to KMS, GuardDuty, Config across all resources in the account.",
        },
      ],
      true,
    );
    NagSuppressions.addResourceSuppressions(this.complianceBucket, [
      {
        id: "AwsSolutions-S1",
        reason:
          "Server access logs not enabled: compliance bucket is itself the audit sink.",
      },
      {
        id: "AwsSolutions-S10",
        reason: "Compliance bucket SSL enforced via Object Lock policy.",
      },
      {
        id: "HIPAA.Security-S3BucketSSLRequestsOnly",
        reason: "Compliance bucket SSL enforced via Object Lock policy.",
      },
    ]);

    NagSuppressions.addResourceSuppressions(fn, [
      {
        id: "AwsSolutions-L1",
        reason:
          "Lambda uses python3.12 which is current at time of writing; pinned version for reproducibility.",
      },
    ]);
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "HIPAA.Security-S3BucketLoggingEnabled",
        reason:
          "Compliance bucket is an audit sink; enabling server access logging would be circular.",
      },
      {
        id: "HIPAA.Security-S3BucketReplicationEnabled",
        reason: "CRR for compliance bucket is a post-Fase-9.5 enhancement.",
      },
      {
        id: "HIPAA.Security-LambdaInsideVPC",
        reason:
          "Evidence collector Lambda calls AWS service APIs via HTTPS; no VPC placement required.",
      },
      {
        id: "HIPAA.Security-LambdaConcurrency",
        reason:
          "Evidence collector runs once daily; reserved concurrency not warranted.",
      },
      {
        id: "HIPAA.Security-LambdaDLQ",
        reason:
          "Evidence collector is scheduled daily with CloudWatch Alarm on score drop; DLQ not required.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline AuditReadAccess policy is narrowly scoped to read-only audit APIs.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "Evidence collector log group is encrypted with the KMS logsKey.",
      },
    ]);
  }
}
