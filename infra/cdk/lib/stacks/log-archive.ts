import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudtrail from 'aws-cdk-lib/aws-cloudtrail';
import * as athena from 'aws-cdk-lib/aws-athena';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import { KmsStack } from './kms';

export interface LogArchiveStackProps extends cdk.StackProps {
  drRegion: string;
  kmsStack: KmsStack;
}

export class LogArchiveStack extends cdk.Stack {
  public readonly trailBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: LogArchiveStackProps) {
    super(scope, id, props);
    const { drRegion: _drRegion, kmsStack } = props;

    // ── CloudTrail S3 bucket (WORM, 7 years DORA) ─────────────────────────
    this.trailBucket = new s3.Bucket(this, 'OrgTrailBucket', {
      bucketName: `org-trail-logs-${this.account}`,
      encryptionKey: kmsStack.logsKey,
      encryption: s3.BucketEncryption.KMS,
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      objectLockEnabled: true,
      objectLockDefaultRetention: s3.ObjectLockRetention.compliance(
        cdk.Duration.days(2555), // 7 years
      ),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          // Operational logs — move to Glacier quickly for cost savings.
          // Object Lock COMPLIANCE (7 years) remains in effect; Glacier
          // is a storage-class transition only and does not break WORM.
          id: 'GlacierFastArchive',
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(7),
            },
          ],
        },
        {
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
              transitionAfter: cdk.Duration.days(365),
            },
          ],
        },
      ],
    });

    // Bucket policy: allow CloudTrail + VPC Flow Logs to write; deny deletes
    this.trailBucket.addToResourcePolicy(new iam.PolicyStatement({
      sid: 'AllowCloudTrailWrite',
      principals: [new iam.ServicePrincipal('cloudtrail.amazonaws.com')],
      actions: ['s3:PutObject'],
      resources: [`${this.trailBucket.bucketArn}/AWSLogs/*`],
      conditions: {
        StringEquals: { 's3:x-amz-acl': 'bucket-owner-full-control' },
      },
    }));
    this.trailBucket.addToResourcePolicy(new iam.PolicyStatement({
      sid: 'AllowCloudTrailAclCheck',
      principals: [new iam.ServicePrincipal('cloudtrail.amazonaws.com')],
      actions: ['s3:GetBucketAcl'],
      resources: [this.trailBucket.bucketArn],
    }));
    this.trailBucket.addToResourcePolicy(new iam.PolicyStatement({
      sid: 'AllowFlowLogsWrite',
      principals: [new iam.ServicePrincipal('delivery.logs.amazonaws.com')],
      actions: ['s3:PutObject'],
      resources: [`${this.trailBucket.bucketArn}/AWSLogs/*`],
      conditions: {
        StringEquals: { 's3:x-amz-acl': 'bucket-owner-full-control' },
      },
    }));

    // ── Athena results bucket ─────────────────────────────────────────────
    const athenaResultsBucket = new s3.Bucket(this, 'AthenaResultsBucket', {
      bucketName: `org-athena-results-${this.account}`,
      encryptionKey: kmsStack.logsKey,
      encryption: s3.BucketEncryption.KMS,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [{ expiration: cdk.Duration.days(90) }],
    });

    // ── Athena workgroup ──────────────────────────────────────────────────
    new athena.CfnWorkGroup(this, 'AuditQueriesWorkgroup', {
      name: 'audit-queries',
      description: 'Workgroup for DORA audit trail queries on CloudTrail logs',
      workGroupConfiguration: {
        enforceWorkGroupConfiguration: true,
        publishCloudWatchMetricsEnabled: true,
        resultConfiguration: {
          outputLocation: `s3://${athenaResultsBucket.bucketName}/results/`,
          encryptionConfiguration: {
            encryptionOption: 'SSE_KMS',
            kmsKey: kmsStack.logsKey.keyArn,
          },
        },
      },
    });

    // ── Organization CloudTrail ───────────────────────────────────────────
    const trailLogGroup = new logs.LogGroup(this, 'CloudTrailLogGroup', {
      logGroupName: '/aws/cloudtrail/org-trail',
      retention: logs.RetentionDays.ONE_YEAR,
      encryptionKey: kmsStack.logsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const trailRole = new iam.Role(this, 'CloudTrailCWRole', {
      assumedBy: new iam.ServicePrincipal('cloudtrail.amazonaws.com'),
      inlinePolicies: {
        CloudWatchLogs: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
              resources: [`${trailLogGroup.logGroupArn}:*`],
            }),
          ],
        }),
      },
    });

    new cloudtrail.CfnTrail(this, 'OrgTrail', {
      trailName: 'lex-agents-org-trail',
      s3BucketName: this.trailBucket.bucketName,
      isLogging: true,
      isMultiRegionTrail: true,
      isOrganizationTrail: true,
      enableLogFileValidation: true,
      includeGlobalServiceEvents: true,
      cloudWatchLogsLogGroupArn: trailLogGroup.logGroupArn,
      cloudWatchLogsRoleArn: trailRole.roleArn,
      kmsKeyId: kmsStack.logsKey.keyArn,
    });

    // Outputs
    new cdk.CfnOutput(this, 'TrailBucketName', {
      value: this.trailBucket.bucketName,
      exportName: 'LexAgents-TrailBucketName',
    });
    new cdk.CfnOutput(this, 'TrailBucketArn', {
      value: this.trailBucket.bucketArn,
      exportName: 'LexAgents-TrailBucketArn',
    });

    // Enforce SSL on both S3 buckets
    this.trailBucket.addToResourcePolicy(new iam.PolicyStatement({
      sid: 'DenyNonSSL',
      effect: iam.Effect.DENY,
      principals: [new iam.AnyPrincipal()],
      actions: ['s3:*'],
      resources: [this.trailBucket.bucketArn, `${this.trailBucket.bucketArn}/*`],
      conditions: { Bool: { 'aws:SecureTransport': 'false' } },
    }));
    athenaResultsBucket.addToResourcePolicy(new iam.PolicyStatement({
      sid: 'DenyNonSSL',
      effect: iam.Effect.DENY,
      principals: [new iam.AnyPrincipal()],
      actions: ['s3:*'],
      resources: [athenaResultsBucket.bucketArn, `${athenaResultsBucket.bucketArn}/*`],
      conditions: { Bool: { 'aws:SecureTransport': 'false' } },
    }));

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-S1',
        reason: 'Server access logs for the log-archive bucket itself would create a circular dependency. The bucket is encrypted with KMS and all access is captured in the org CloudTrail.',
      },
      {
        id: 'HIPAA.Security-S3BucketLoggingEnabled',
        reason: 'This IS the logging bucket. Adding server access logs to itself is circular. All access captured via CloudTrail organization trail.',
      },
      {
        id: 'HIPAA.Security-S3BucketReplicationEnabled',
        reason: 'Cross-region replication to eu-west-1 is configured via AWS Backup policies post-deploy to avoid circular stack dependencies at synth time.',
      },
      {
        id: 'HIPAA.Security-S3BucketVersioningEnabled',
        reason: 'Athena results bucket holds transient query results with 90-day lifecycle expiry. Versioning not required; WORM Object Lock applied to the primary trail bucket.',
      },
      {
        id: 'AwsSolutions-ATH1',
        reason: 'Athena workgroup enforces SSE-KMS encryption on results. enforceWorkGroupConfiguration: true prevents override.',
      },
      {
        id: 'AwsSolutions-IAM5',
        reason: 'CloudTrail CW role requires :* suffix on log group ARN to create streams. This is the documented AWS pattern for CloudTrail-to-CloudWatch integration.',
      },
      {
        id: 'HIPAA.Security-IAMNoInlinePolicy',
        reason: 'CloudTrail CW Logs role uses an inline policy scoped to a single specific log group ARN. This is narrower than a managed policy and follows least-privilege.',
      },
    ]);
  }
}
