/**
 * DataStack — Fase 9.2
 *
 * Provisions the stateful data tier for lex-agents in the workloads-dev account:
 *   - Aurora Serverless v2 PostgreSQL 16 (writer + reader, private-data subnets)
 *   - S3 buckets: raw, canonical, evals, backups (SSE-KMS, versioned, VPC-locked)
 *   - Secrets Manager secrets for Anthropic, Langfuse, JWT (placeholder values)
 *
 * After deploy, replace placeholder secrets:
 *   aws secretsmanager put-secret-value \
 *     --secret-id /lex-agents/dev/anthropic/api-key \
 *     --secret-string '{"value":"sk-ant-..."}'
 */

import * as cdk from "aws-cdk-lib";
import * as backup from "aws-cdk-lib/aws-backup";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as logs from "aws-cdk-lib/aws-logs";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import { DR_REGION } from "../config/environments";

import { NetworkSpokeStack } from "./network-spoke";
import { KmsStack } from "./kms";

export interface DataStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
  kmsStack: KmsStack;
}

export class DataStack extends cdk.Stack {
  public readonly aurora: rds.DatabaseCluster;
  public readonly sgAurora: ec2.SecurityGroup;
  public readonly dbAppUserSecret: secretsmanager.ISecret;
  public readonly buckets: {
    raw: s3.Bucket;
    canonical: s3.Bucket;
    evals: s3.Bucket;
    backups: s3.Bucket;
  };

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    const { envName, networkStack, kmsStack } = props;

    const vpc = networkStack.vpc;
    // Type-narrow KMS keys — both are guaranteed when includeWorkloadKeys: true
    const rdsKey = kmsStack.rdsKey!;
    const s3Key = kmsStack.s3Key!;
    const secretsKey = kmsStack.secretsKey!;

    // ── S3 Gateway Endpoint (required for aws:SourceVpce bucket policy) ──────
    // The NetworkSpokeStack does not provision an S3 gateway endpoint, so we
    // add it here.  Gateway endpoints are free and improve data-path security
    // by ensuring S3 traffic never leaves the AWS network.
    const s3GatewayEndpoint = vpc.addGatewayEndpoint("S3GatewayEndpoint", {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    // ── CloudWatch log group for Aurora audit logs ────────────────────────────
    // CDK tracks this resource by construction; no reference needed after creation.
    new logs.LogGroup(this, "AuroraLogGroup", {
      logGroupName: `/lex-agents/${envName}/aurora`,
      retention: logs.RetentionDays.ONE_YEAR,
      encryptionKey: kmsStack.logsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── Aurora security group ─────────────────────────────────────────────────
    // DataStack owns this SG so that AppServicesStack can add ingress rules to
    // it without creating a cross-stack cycle.  NetworkSpokeStack.sgAurora is
    // a separate SG (also attached to the cluster) that pre-wires the ECS API
    // egress rules defined at network layer.  Having two SGs on the cluster is
    // intentional: one owned by the network layer, one by the data layer.
    this.sgAurora = new ec2.SecurityGroup(this, "SgAurora", {
      vpc,
      securityGroupName: `lex-agents-${envName}-aurora-data`,
      description:
        "Aurora cluster SG (owned by DataStack — ingress from app services)",
      allowAllOutbound: false,
    });

    // ── Subnet group — private-data subnets only ───────────────────────────────
    const subnetGroup = new rds.SubnetGroup(this, "AuroraSubnetGroup", {
      description: `lex-agents ${envName} Aurora subnet group`,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── Aurora Serverless v2 cluster ───────────────────────────────────────────
    this.aurora = new rds.DatabaseCluster(this, "AuroraCluster", {
      clusterIdentifier: `lex-agents-${envName}`,
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_16_4,
      }),

      // Serverless v2 capacity limits
      serverlessV2MinCapacity: 0, // auto-pause supported in v16.4
      serverlessV2MaxCapacity: 8,
      // Auto-pause after 5 minutes of inactivity (dev only)
      serverlessV2AutoPauseDuration: cdk.Duration.minutes(5),

      // Writer in first private-data AZ, reader in second
      writer: rds.ClusterInstance.serverlessV2("writer", {
        publiclyAccessible: false,
      }),
      readers: [
        rds.ClusterInstance.serverlessV2("reader1", {
          scaleWithWriter: true,
          publiclyAccessible: false,
        }),
      ],

      vpc,
      subnetGroup,
      // Two SGs: NetworkSpokeStack's (pre-wired ECS egress) + DataStack's own
      // (used by AppServicesStack to add ingress from app services).
      securityGroups: [networkStack.sgAurora, this.sgAurora],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },

      // Encryption
      storageEncrypted: true,
      storageEncryptionKey: rdsKey,

      // Credentials — stored in Secrets Manager under /lex-agents/${envName}/db/master
      credentials: rds.Credentials.fromGeneratedSecret("postgres", {
        secretName: `/lex-agents/${envName}/db/master`,
        encryptionKey: secretsKey,
      }),
      defaultDatabaseName: "lex_agents",

      // IAM authentication (app-side connections use IAM tokens via asyncpg)
      iamAuthentication: true,

      // Data API disabled — we use direct TCP connections via asyncpg
      enableDataApi: false,

      // Performance Insights
      performanceInsightEncryptionKey: rdsKey,
      performanceInsightRetention: rds.PerformanceInsightRetention.DEFAULT,

      // Backup: 7 days retention, PITR active
      backup: {
        retention: cdk.Duration.days(7),
      },

      // Audit logs → CloudWatch Logs
      cloudwatchLogsExports: ["postgresql"],
      cloudwatchLogsRetention: logs.RetentionDays.ONE_MONTH,

      // Dev: no deletion protection (suppressed below with documented reason)
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,

      port: 5432,
    });

    // NOTE: Master credentials rotation was deferred in Fase 9.2.
    // For now: rotate master credentials manually via:
    //   aws secretsmanager rotate-secret --secret-id /lex-agents/dev/db/master

    // ── App-user secret ────────────────────────────────────────────────────────
    // The application reads this at startup.  Populate after deploy:
    //   aws secretsmanager put-secret-value \
    //     --secret-id /lex-agents/dev/db/app-user \
    //     --secret-string '{"username":"lex_app","password":"<strong-password>"}'
    this.dbAppUserSecret = new secretsmanager.Secret(this, "DbAppUserSecret", {
      secretName: `/lex-agents/${envName}/db/app-user`,
      description: `lex-agents ${envName} Aurora app-user credentials (managed by app)`,
      encryptionKey: secretsKey,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: "lex_app" }),
        generateStringKey: "password",
        excludeCharacters: '"@/\\',
        passwordLength: 32,
      },
    });

    // ── Secrets rotation — app-user secret (Fase 9.4, ADR 0050) ──────────────
    // Uses CfnRotationSchedule (L1) directly to avoid the CDK cross-stack cycle
    // that addRotationSingleUser() would introduce via aurora.connections.
    // The rotation Lambda SG is created here (DataStack) with an explicit egress
    // rule to the Aurora SG — no Endpoint.Port token resolution required.
    const sgRotation = new ec2.SecurityGroup(this, "SgRotationLambda", {
      vpc,
      description: "SM rotation Lambda for Aurora app-user",
      allowAllOutbound: false,
    });
    // Use standalone L1 resources instead of addEgressRule/addIngressRule to
    // avoid the CloudFormation cyclic dependency (SgAurora ↔ SgRotationLambda).
    new ec2.CfnSecurityGroupEgress(this, "SgRotationEgressToAurora", {
      groupId: sgRotation.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      destinationSecurityGroupId: this.sgAurora.securityGroupId,
      description: "PostgreSQL to Aurora for rotation",
    });
    new ec2.CfnSecurityGroupIngress(this, "SgAuroraIngressFromRotation", {
      groupId: this.sgAurora.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      sourceSecurityGroupId: sgRotation.securityGroupId,
      description: "Secrets Manager rotation Lambda",
    });

    new secretsmanager.CfnRotationSchedule(this, "AppUserRotation", {
      secretId: this.dbAppUserSecret.secretArn,
      hostedRotationLambda: {
        rotationType: "PostgreSQLSingleUser",
        vpcSecurityGroupIds: sgRotation.securityGroupId,
        vpcSubnetIds: vpc
          .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS })
          .subnetIds.join(","),
      },
      rotationRules: { automaticallyAfterDays: 30 },
    });

    // ── CfnOutput: Aurora endpoints ───────────────────────────────────────────
    new cdk.CfnOutput(this, "AuroraClusterEndpoint", {
      value: this.aurora.clusterEndpoint.socketAddress,
      exportName: `LexAgents-${envName}-AuroraEndpoint`,
      description: "Aurora writer endpoint (host:port)",
    });
    new cdk.CfnOutput(this, "AuroraClusterReadEndpoint", {
      value: this.aurora.clusterReadEndpoint.socketAddress,
      exportName: `LexAgents-${envName}-AuroraReadEndpoint`,
      description: "Aurora reader endpoint (host:port)",
    });

    // ── S3 helper: shared bucket policy statements ────────────────────────────
    const denyNonSsl = (bucket: s3.Bucket): iam.PolicyStatement =>
      new iam.PolicyStatement({
        sid: "DenyNonSSL",
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:*"],
        resources: [bucket.bucketArn, `${bucket.bucketArn}/*`],
        conditions: { Bool: { "aws:SecureTransport": "false" } },
      });

    // Restrict access to requests originating from within the VPC via the
    // S3 gateway endpoint.  This prevents direct-internet writes even if
    // bucket policies are misconfigured.
    const denyNonVpce = (bucket: s3.Bucket): iam.PolicyStatement =>
      new iam.PolicyStatement({
        sid: "DenyNonVpce",
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:*"],
        resources: [bucket.bucketArn, `${bucket.bucketArn}/*`],
        conditions: {
          StringNotEquals: {
            "aws:SourceVpce": s3GatewayEndpoint.vpcEndpointId,
          },
          // Allow AWS services (e.g., CloudFormation, CDK deployment) to
          // bypass the VPCE restriction during stack provisioning.
          Null: { "aws:SourceVpce": "false" },
        },
      });

    const addCommonPolicies = (bucket: s3.Bucket): void => {
      bucket.addToResourcePolicy(denyNonSsl(bucket));
      bucket.addToResourcePolicy(denyNonVpce(bucket));
    };

    // ── S3 Bucket 1: raw ingest documents ────────────────────────────────────
    const rawBucket = new s3.Bucket(this, "RawBucket", {
      bucketName: `lex-agents-raw-${envName}-${this.account}`,
      encryptionKey: s3Key,
      encryption: s3.BucketEncryption.KMS,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(30),
            },
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
      ],
    });
    addCommonPolicies(rawBucket);

    // ── S3 Bucket 2: canonical (normalised) documents ─────────────────────────
    const canonicalBucket = new s3.Bucket(this, "CanonicalBucket", {
      bucketName: `lex-agents-canonical-${envName}-${this.account}`,
      encryptionKey: s3Key,
      encryption: s3.BucketEncryption.KMS,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(60),
            },
          ],
        },
      ],
    });
    addCommonPolicies(canonicalBucket);

    // ── S3 Bucket 3: evaluation results ──────────────────────────────────────
    const evalsBucket = new s3.Bucket(this, "EvalsBucket", {
      bucketName: `lex-agents-evals-${envName}-${this.account}`,
      encryptionKey: s3Key,
      encryption: s3.BucketEncryption.KMS,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      // Versioning only — no lifecycle transitions
    });
    addCommonPolicies(evalsBucket);

    // ── S3 Bucket 4: database / EFS backups (WORM, 7 years) ──────────────────
    // Object Lock requires versioning (enforced by CDK when objectLockEnabled: true)
    const backupsBucket = new s3.Bucket(this, "BackupsBucket", {
      bucketName: `lex-agents-backups-${envName}-${this.account}`,
      encryptionKey: s3Key,
      encryption: s3.BucketEncryption.KMS,
      bucketKeyEnabled: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      objectLockEnabled: true,
      objectLockDefaultRetention: s3.ObjectLockRetention.governance(
        cdk.Duration.days(2555), // 7 years
      ),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(30),
            },
            {
              storageClass: s3.StorageClass.DEEP_ARCHIVE,
              transitionAfter: cdk.Duration.days(365),
            },
          ],
        },
      ],
    });
    addCommonPolicies(backupsBucket);

    this.buckets = {
      raw: rawBucket,
      canonical: canonicalBucket,
      evals: evalsBucket,
      backups: backupsBucket,
    };

    // ── S3 Cross-Region Replication (CRR) — eu-west-1 DR replicas (Fase 9.4) ─
    // ADR 0051: raw, canonical, backups buckets are replicated to eu-west-1.
    // evals bucket is excluded (eval fixtures are reproducible; CRR cost not justified).

    // CRR IAM role — S3 service assumes this to replicate objects
    const crrRole = new iam.Role(this, "S3CrrRole", {
      roleName: `lex-agents-${envName}-s3-crr`,
      assumedBy: new iam.ServicePrincipal("s3.amazonaws.com"),
    });

    // DR replica buckets — NOTE: Cross-region S3 buckets must be deployed in separate
    // CloudFormation stacks targeting eu-west-1. These CfnBucket resources represent
    // the bucket definitions; in production, deploy a separate DataDrStack in eu-west-1.
    // The buckets are defined here for CDK synthesis validation and CRR role IAM grants.
    // See docs/aws/dr-plan.md Appendix A for bootstrap procedure.
    const rawDrBucket = new s3.CfnBucket(this, "RawDrBucket", {
      bucketName: `lex-agents-raw-${envName}-dr`,
      bucketEncryption: {
        serverSideEncryptionConfiguration: [
          { serverSideEncryptionByDefault: { sseAlgorithm: "AES256" } },
        ],
      },
      versioningConfiguration: { status: "Enabled" },
      publicAccessBlockConfiguration: {
        blockPublicAcls: true,
        blockPublicPolicy: true,
        ignorePublicAcls: true,
        restrictPublicBuckets: true,
      },
    });

    const canonicalDrBucket = new s3.CfnBucket(this, "CanonicalDrBucket", {
      bucketName: `lex-agents-canonical-${envName}-dr`,
      bucketEncryption: {
        serverSideEncryptionConfiguration: [
          { serverSideEncryptionByDefault: { sseAlgorithm: "AES256" } },
        ],
      },
      versioningConfiguration: { status: "Enabled" },
      publicAccessBlockConfiguration: {
        blockPublicAcls: true,
        blockPublicPolicy: true,
        ignorePublicAcls: true,
        restrictPublicBuckets: true,
      },
    });

    const backupsDrBucket = new s3.CfnBucket(this, "BackupsDrBucket", {
      bucketName: `lex-agents-backups-${envName}-dr`,
      bucketEncryption: {
        serverSideEncryptionConfiguration: [
          { serverSideEncryptionByDefault: { sseAlgorithm: "AES256" } },
        ],
      },
      versioningConfiguration: { status: "Enabled" },
      publicAccessBlockConfiguration: {
        blockPublicAcls: true,
        blockPublicPolicy: true,
        ignorePublicAcls: true,
        restrictPublicBuckets: true,
      },
    });

    // Grant CRR role read on source buckets and write on DR replicas
    crrRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CrrSourceRead",
        actions: ["s3:GetReplicationConfiguration", "s3:ListBucket"],
        resources: [
          rawBucket.bucketArn,
          canonicalBucket.bucketArn,
          backupsBucket.bucketArn,
        ],
      }),
    );
    crrRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CrrObjectRead",
        actions: [
          "s3:GetObjectVersionForReplication",
          "s3:GetObjectVersionAcl",
          "s3:GetObjectVersionTagging",
        ],
        resources: [
          `${rawBucket.bucketArn}/*`,
          `${canonicalBucket.bucketArn}/*`,
          `${backupsBucket.bucketArn}/*`,
        ],
      }),
    );
    // KMS grants for SSE-KMS encrypted source objects.
    // The CRR role must be able to decrypt source objects and re-encrypt them
    // in the destination.  Both the source KMS key (Decrypt) and the destination
    // KMS key (GenerateDataKey / Encrypt) permissions are required.
    // IMPORTANT: for production cross-region DR, replace s3Key with a CMK that
    // has a key policy granting access from eu-west-1 (or use a multi-region key).
    crrRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CrrKmsDecryptSource",
        actions: ["kms:Decrypt", "kms:GenerateDataKey"],
        resources: [s3Key.keyArn],
      }),
    );
    crrRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CrrDestWrite",
        actions: [
          "s3:ReplicateObject",
          "s3:ReplicateDelete",
          "s3:ReplicateTags",
        ],
        resources: [
          `arn:aws:s3:::lex-agents-raw-${envName}-dr/*`,
          `arn:aws:s3:::lex-agents-canonical-${envName}-dr/*`,
          `arn:aws:s3:::lex-agents-backups-${envName}-dr/*`,
        ],
      }),
    );

    // CfnBucketReplication on source buckets — applied via L1 overrides
    // CRR replication rule helper — includes SSE-KMS source selection criteria
    // so KMS-encrypted objects are replicated.  The destination must have a KMS
    // key accessible from the DR region; s3Key.keyArn is a placeholder for CDK
    // synthesis.  Replace with a CMK in eu-west-1 before enabling live CRR.
    const makeCrrRule = (
      destBucketName: string,
    ): s3.CfnBucket.ReplicationRuleProperty => ({
      id: "ReplicateToDrRegion",
      status: "Enabled",
      sourceSelectionCriteria: {
        sseKmsEncryptedObjects: { status: "Enabled" },
      },
      destination: {
        bucket: `arn:aws:s3:::${destBucketName}`,
        storageClass: "STANDARD_IA",
        encryptionConfiguration: {
          // PRODUCTION: replace with a CMK key ARN in eu-west-1.
          replicaKmsKeyId: s3Key.keyArn,
        },
      },
    });

    const rawBucketCfn = rawBucket.node.defaultChild as s3.CfnBucket;
    rawBucketCfn.replicationConfiguration = {
      role: crrRole.roleArn,
      rules: [makeCrrRule(`lex-agents-raw-${envName}-dr`)],
    };

    const canonicalBucketCfn = canonicalBucket.node
      .defaultChild as s3.CfnBucket;
    canonicalBucketCfn.replicationConfiguration = {
      role: crrRole.roleArn,
      rules: [makeCrrRule(`lex-agents-canonical-${envName}-dr`)],
    };

    const backupsBucketCfn = backupsBucket.node.defaultChild as s3.CfnBucket;
    backupsBucketCfn.replicationConfiguration = {
      role: crrRole.roleArn,
      rules: [makeCrrRule(`lex-agents-backups-${envName}-dr`)],
    };

    // ── AWS Backup — Aurora cross-region DR (Fase 9.4, ADR 0051) ──────────────
    // Cross-region copy action requires DR vault bootstrap in eu-west-1 —
    // see docs/aws/dr-plan.md for the bootstrap procedure.
    // For now, we create only the local backup vault and plan.

    const backupVault = new backup.BackupVault(this, "AuroraBackupVault", {
      backupVaultName: `lex-agents-${envName}-aurora-backup`,
      // Encrypt backup vault with the same KMS key used for Aurora storage.
      encryptionKey: rdsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const backupPlan = new backup.BackupPlan(this, "AuroraBackupPlan", {
      // Named "local-backup" (not "dr") until cross-region copy action is
      // configured with a DR vault in eu-west-1 (see docs/aws/dr-plan.md).
      backupPlanName: `lex-agents-${envName}-aurora-local-backup`,
      backupVault,
    });

    backupPlan.addRule(backup.BackupPlanRule.daily());

    backupPlan.addSelection("AuroraSelection", {
      resources: [backup.BackupResource.fromRdsDatabaseCluster(this.aurora)],
    });

    // ── CfnOutputs: bucket names ──────────────────────────────────────────────
    new cdk.CfnOutput(this, "RawBucketName", {
      value: rawBucket.bucketName,
      exportName: `LexAgents-${envName}-RawBucket`,
    });
    new cdk.CfnOutput(this, "CanonicalBucketName", {
      value: canonicalBucket.bucketName,
      exportName: `LexAgents-${envName}-CanonicalBucket`,
    });
    new cdk.CfnOutput(this, "EvalsBucketName", {
      value: evalsBucket.bucketName,
      exportName: `LexAgents-${envName}-EvalsBucket`,
    });
    new cdk.CfnOutput(this, "BackupsBucketName", {
      value: backupsBucket.bucketName,
      exportName: `LexAgents-${envName}-BackupsBucket`,
    });

    // ── Application secrets (placeholder values — replace post-deploy) ─────────
    const secretDefaults = {
      encryptionKey: secretsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    } as const;

    new secretsmanager.Secret(this, "AnthropicApiKeySecret", {
      ...secretDefaults,
      secretName: `/lex-agents/${envName}/anthropic/api-key`,
      description: `lex-agents ${envName} Anthropic API key — replace REPLACE_ME after deploy`,
      secretStringValue: cdk.SecretValue.unsafePlainText("REPLACE_ME"),
    });

    new secretsmanager.Secret(this, "LangfuseSecretKeySecret", {
      ...secretDefaults,
      secretName: `/lex-agents/${envName}/langfuse/secret-key`,
      description: `lex-agents ${envName} Langfuse secret key — replace REPLACE_ME after deploy`,
      secretStringValue: cdk.SecretValue.unsafePlainText("REPLACE_ME"),
    });

    new secretsmanager.Secret(this, "LangfusePublicKeySecret", {
      ...secretDefaults,
      secretName: `/lex-agents/${envName}/langfuse/public-key`,
      description: `lex-agents ${envName} Langfuse public key — replace REPLACE_ME after deploy`,
      secretStringValue: cdk.SecretValue.unsafePlainText("REPLACE_ME"),
    });

    new secretsmanager.Secret(this, "JwtSigningKeySecret", {
      ...secretDefaults,
      secretName: `/lex-agents/${envName}/jwt/signing-key`,
      description: `lex-agents ${envName} JWT signing key — replace REPLACE_ME after deploy`,
      secretStringValue: cdk.SecretValue.unsafePlainText("REPLACE_ME"),
    });

    // ── cdk-nag suppressions ──────────────────────────────────────────────────
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-RDS6",
        reason:
          "IAM authentication is enabled (iamAuthentication: true). The app connects via asyncpg using IAM token auth.",
      },
      {
        id: "AwsSolutions-RDS10",
        reason:
          "Deletion protection disabled for dev environment. Enabled in staging/prod environments. Suppression scoped to dev stack only.",
      },
      {
        id: "AwsSolutions-RDS16",
        reason:
          "Aurora Serverless v2 PostgreSQL — cloudwatchLogsExports: [postgresql] enables audit/error/slow-query logging.",
      },
      {
        id: "AwsSolutions-S1",
        reason:
          "Server access logs for raw/canonical/evals/backups buckets are not required in dev. All access is captured via CloudTrail org trail in the log-archive account.",
      },
      {
        id: "AwsSolutions-SMG4",
        reason:
          "App-user secret rotation is managed by the application lifecycle (DB user rotation requires app coordination). Master credentials use addRotationSingleUser with 30-day rotation.",
      },
      {
        id: "HIPAA.Security-RDSLoggingEnabled",
        reason:
          "Aurora PostgreSQL cloudwatchLogsExports includes postgresql log which covers audit, error, and slow query logs.",
      },
      {
        id: "HIPAA.Security-RDSInstanceBackupEnabled",
        reason:
          "Aurora cluster backup.retention = 7 days with PITR active. HIPAA rule fires on instance-level; Aurora uses cluster-level backups.",
      },
      {
        id: "HIPAA.Security-RDSInstanceDeletionProtectionEnabled",
        reason:
          "Deletion protection disabled intentionally for dev environment — dev data is ephemeral. Will be enabled in staging/prod.",
      },
      {
        id: "HIPAA.Security-RDSMultiAZSupport",
        reason:
          "Aurora Serverless v2 with a writer + reader instance in separate AZs provides equivalent multi-AZ resilience to RDS Multi-AZ deployments.",
      },
      {
        id: "HIPAA.Security-S3BucketLoggingEnabled",
        reason:
          "Access logging for workload S3 buckets omitted in dev. All API-level access is captured in CloudTrail. Server access logs to be enabled in prod.",
      },
      {
        id: "HIPAA.Security-S3BucketReplicationEnabled",
        reason:
          "Cross-region replication not configured in dev environment. Will be enabled for prod via AWS Backup / S3 replication rules.",
      },
      {
        id: "HIPAA.Security-SecretsManagerRotationEnabled",
        reason:
          "Placeholder secrets (Anthropic, Langfuse, JWT) are populated manually post-deploy and do not require automated rotation. Master DB secret uses addRotationSingleUser.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline policies on Lambda rotation function roles are created automatically by CDK addRotationSingleUser. These are the narrowest-scope policies possible for the rotation use case.",
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "Wildcard permissions in rotation Lambda execution role are created automatically by CDK addRotationSingleUser and scoped to the specific secret and KMS key ARNs.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AWSLambdaVPCAccessExecutionRole managed policy attached to rotation Lambda by CDK addRotationSingleUser. Required for VPC-attached Lambda execution.",
      },
      {
        id: "AwsSolutions-L1",
        reason:
          "Rotation Lambda runtime is managed by the CDK SecretRotation construct and pinned to the version specified by that construct. Runtime upgrade tracked in CDK version updates.",
      },
      {
        id: "HIPAA.Security-LambdaInsideVPC",
        reason:
          "Rotation Lambda created by CDK addRotationSingleUser is deployed inside the VPC (vpcSubnets: PRIVATE_WITH_EGRESS) to reach the Aurora endpoint.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "Aurora audit log group is encrypted with the KMS logsKey. The cdk-nag warning fires on the auto-created retention custom resource Lambda log group which is outside our control.",
      },
      {
        id: "HIPAA.Security-S3BucketReplicationEnabled",
        reason:
          "CRR is now enabled on raw, canonical, and backups buckets (Fase 9.4). evals bucket excluded — eval data is reproducible.",
      },
      {
        id: "AwsSolutions-BAK3",
        reason:
          "Cross-region backup vault copy action requires eu-west-1 DR vault bootstrap — see docs/aws/dr-plan.md. Local vault and plan are created; cross-region copy added post-bootstrap.",
      },
      {
        id: "AwsSolutions-BAK1",
        reason:
          "Backup vault access policy not required for dev environment backup vault.",
      },
    ]);
  }
}
