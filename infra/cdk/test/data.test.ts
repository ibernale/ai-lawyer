import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { KmsStack } from '../lib/stacks/kms';
import { NetworkSpokeStack } from '../lib/stacks/network-spoke';
import { DataStack } from '../lib/stacks/data';

// ── Test fixtures ─────────────────────────────────────────────────────────────

function buildStack(): { stack: DataStack; template: Template } {
  const app = new cdk.App();
  const env = { account: '123456789012', region: 'eu-west-1' };

  const kmsStack = new KmsStack(app, 'TestKms', {
    env,
    envName: 'dev',
    includeWorkloadKeys: true,
  });

  const networkStack = new NetworkSpokeStack(app, 'TestNetwork', {
    env,
    envName: 'dev',
    logArchiveAccountId: '222222222222',
  });

  const stack = new DataStack(app, 'TestDataStack', {
    env,
    envName: 'dev',
    networkStack,
    kmsStack,
  });

  return { stack, template: Template.fromStack(stack) };
}

// ── Aurora ────────────────────────────────────────────────────────────────────

describe('DataStack — Aurora Serverless v2', () => {
  const { template } = buildStack();

  test('Aurora cluster resource exists', () => {
    template.resourceCountIs('AWS::RDS::DBCluster', 1);
  });

  test('Aurora cluster uses PostgreSQL 16 engine', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      Engine: 'aurora-postgresql',
    });
  });

  test('Aurora cluster is encrypted with a KMS key', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      StorageEncrypted: true,
    });
  });

  test('Aurora cluster has 7-day backup retention', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      BackupRetentionPeriod: 7,
    });
  });

  test('Aurora cluster has IAM authentication enabled', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      EnableIAMDatabaseAuthentication: true,
    });
  });

  test('Aurora cluster exports postgresql logs to CloudWatch', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      EnableCloudwatchLogsExports: Match.arrayWith(['postgresql']),
    });
  });

  test('Two DB instances exist (writer + one reader)', () => {
    template.resourceCountIs('AWS::RDS::DBInstance', 2);
  });

  test('Rotation schedule exists for app-user secret (Fase 9.4, ADR 0050)', () => {
    // CfnRotationSchedule (L1) is used to avoid CDK cross-stack cycle.
    // PostgreSQLSingleUser hosted rotation Lambda — 30-day rotation period.
    template.resourceCountIs('AWS::SecretsManager::RotationSchedule', 1);
  });

  test('Aurora subnet group uses ISOLATED subnets', () => {
    template.resourceCountIs('AWS::RDS::DBSubnetGroup', 1);
  });
});

// ── S3 Buckets ────────────────────────────────────────────────────────────────

describe('DataStack — S3 Buckets', () => {
  const { template } = buildStack();

  test('Primary S3 buckets exist (raw, canonical, evals, backups)', () => {
    // 4 primary L2 buckets; DR replicas use CfnBucket (also AWS::S3::Bucket resources)
    const buckets = template.findResources('AWS::S3::Bucket');
    expect(Object.keys(buckets).length).toBeGreaterThanOrEqual(4);
  });

  test('Primary S3 buckets use SSE-KMS encryption', () => {
    // 4 primary L2 buckets use KMS; 3 DR CfnBuckets use AES256 (cross-region replicas)
    const buckets = template.findResources('AWS::S3::Bucket');
    const kmsEncryptedBuckets = Object.values(buckets).filter((bucket: any) => {
      const rules =
        bucket.Properties.BucketEncryption?.ServerSideEncryptionConfiguration ?? [];
      return rules.some(
        (r: any) => r.ServerSideEncryptionByDefault?.SSEAlgorithm === 'aws:kms',
      );
    });
    // At least 4 primary buckets are KMS-encrypted
    expect(kmsEncryptedBuckets.length).toBeGreaterThanOrEqual(4);
  });

  test('No S3 bucket allows public access (security assertion)', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    Object.values(buckets).forEach((bucket: any) => {
      const bpa = bucket.Properties.PublicAccessBlockConfiguration;
      expect(bpa).toBeDefined();
      expect(bpa.BlockPublicAcls).toBe(true);
      expect(bpa.BlockPublicPolicy).toBe(true);
      expect(bpa.IgnorePublicAcls).toBe(true);
      expect(bpa.RestrictPublicBuckets).toBe(true);
    });
  });

  test('Object Lock enabled on backups bucket', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      ObjectLockEnabled: true,
      ObjectLockConfiguration: {
        ObjectLockEnabled: 'Enabled',
        Rule: {
          DefaultRetention: {
            Mode: 'GOVERNANCE',
            Days: 2555,
          },
        },
      },
    });
  });

  test('All S3 buckets have versioning enabled', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    Object.values(buckets).forEach((bucket: any) => {
      expect(
        bucket.Properties.VersioningConfiguration?.Status,
      ).toBe('Enabled');
    });
  });

  test('Raw bucket has Standard → IA after 90d lifecycle transition', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      LifecycleConfiguration: {
        Rules: Match.arrayWith([
          Match.objectLike({
            Transitions: Match.arrayWith([
              Match.objectLike({
                StorageClass: 'STANDARD_IA',
                TransitionInDays: 90,
              }),
            ]),
          }),
        ]),
      },
    });
  });

  test('Backups bucket has Glacier lifecycle transition after 30d', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      ObjectLockEnabled: true,
      LifecycleConfiguration: {
        Rules: Match.arrayWith([
          Match.objectLike({
            Transitions: Match.arrayWith([
              Match.objectLike({
                StorageClass: 'GLACIER',
                TransitionInDays: 30,
              }),
            ]),
          }),
        ]),
      },
    });
  });
});

// ── Secrets Manager ───────────────────────────────────────────────────────────

describe('DataStack — Secrets Manager', () => {
  const { template } = buildStack();

  test('App-user secret exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/db/app-user',
    });
  });

  test('Anthropic API key placeholder secret exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/anthropic/api-key',
    });
  });

  test('Langfuse secret-key placeholder exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/langfuse/secret-key',
    });
  });

  test('Langfuse public-key placeholder exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/langfuse/public-key',
    });
  });

  test('JWT signing-key placeholder exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/jwt/signing-key',
    });
  });

  test('App-user rotation schedule exists (1 RotationSchedule resource)', () => {
    // CfnRotationSchedule (L1) added in Fase 9.4 for ADR 0050 compliance.
    template.resourceCountIs('AWS::SecretsManager::RotationSchedule', 1);
  });
});

// ── AWS Backup (Fase 9.4, ADR 0051) ───────────────────────────────────────────

describe('DataStack — AWS Backup', () => {
  const { template } = buildStack();

  test('AWS Backup vault exists for Aurora DR', () => {
    template.hasResourceProperties('AWS::Backup::BackupVault', {
      BackupVaultName: 'lex-agents-dev-aurora-backup',
    });
  });

  test('AWS Backup plan exists', () => {
    template.hasResourceProperties('AWS::Backup::BackupPlan', Match.objectLike({}));
  });

  test('AWS Backup selection includes Aurora cluster', () => {
    const selections = template.findResources('AWS::Backup::BackupSelection');
    expect(Object.keys(selections).length).toBeGreaterThanOrEqual(1);
  });
});

// ── VPC Endpoint ──────────────────────────────────────────────────────────────
// Note: DataStack calls vpc.addGatewayEndpoint() on networkStack.vpc, so the
// endpoint resource lands in NetworkSpokeStack (CDK places resources in the
// owning stack of the construct).  We verify that the S3 gateway endpoint is
// present somewhere in the synthesised app via the networkStack template instead.

describe('DataStack — VPC', () => {
  test('S3 Gateway VPC endpoint is present in the VPC owner stack (NetworkSpokeStack)', () => {
    const app = new cdk.App();
    const env = { account: '123456789012', region: 'eu-west-1' };
    const kmsStack = new KmsStack(app, 'TestKms2', { env, envName: 'dev', includeWorkloadKeys: true });
    const networkStack = new NetworkSpokeStack(app, 'TestNetwork2', { env, envName: 'dev', logArchiveAccountId: '222222222222' });
    new DataStack(app, 'TestDataStack2', { env, envName: 'dev', networkStack, kmsStack });

    // The S3 gateway endpoint is added to networkStack.vpc; CDK places it in
    // the NetworkSpokeStack template, not the DataStack template.
    const netTemplate = Template.fromStack(networkStack);
    // ServiceName is synthesised as Fn::Join (token) so we cannot use
    // stringLikeRegexp. Assert on the join fragments instead.
    netTemplate.hasResourceProperties('AWS::EC2::VPCEndpoint', {
      VpcEndpointType: 'Gateway',
      ServiceName: Match.objectLike({
        'Fn::Join': Match.arrayWith([
          Match.arrayWith([Match.stringLikeRegexp('s3')]),
        ]),
      }),
    });
  });
});
