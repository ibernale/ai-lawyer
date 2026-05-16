/**
 * LangfuseStack — Fase 9.4
 *
 * Deploys Langfuse v2 LLM observability platform on ECS Fargate with a
 * dedicated Aurora Serverless v2 PostgreSQL backend (ADR 0048).
 * (Pinned to :2 — v3 requires ClickHouse/Redis/S3 not yet provisioned.)
 *
 * Architecture:
 *   - Internal ALB (not internet-facing) on port 443
 *   - ECS Fargate service: langfuse-web (ghcr.io/langfuse/langfuse:2)
 *   - Aurora Serverless v2 (PG 16), minCapacity 0.5 (never fully pauses)
 *   - Secrets Manager: nextauth-secret, salt, encryption-key
 *   - DATABASE_URL assembled at container startup from Aurora master secret
 *     fields (no Lambda custom resource — eliminates ResourceInitializationError
 *     caused by custom-resource secrets being deleted on CFn rollbacks)
 *
 * TODO: langfuse-worker ECS service: add when event-processing queue exceeds
 * web capacity (LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES=false means web handles
 * both roles in MVP).
 *
 * Access: internal ALB only. Use SSM Session Manager port-forward for admin:
 *   aws ssm start-session --target <task-id> --document-name AWS-StartPortForwardingSession
 */

import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import type { NetworkSpokeStack } from "./network-spoke";

export interface LangfuseStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
}

export class LangfuseStack extends cdk.Stack {
  /** Internal ALB DNS name for Langfuse (VPC-only). */
  public readonly langfuseUrl: string;
  public readonly langfuseAurora: rds.IDatabaseCluster;
  /** Secrets Manager secret holding LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.
   *  Populate post-deploy: aws secretsmanager put-secret-value --secret-id <arn>
   *    --secret-string '{"LANGFUSE_PUBLIC_KEY":"pk-lf-...","LANGFUSE_SECRET_KEY":"sk-lf-..."}' */
  public readonly langfuseApiKeysSecret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props: LangfuseStackProps) {
    super(scope, id, props);
    const { envName, networkStack } = props;
    const vpc = networkStack.vpc;

    // ── Security groups ───────────────────────────────────────────────────────

    const sgLangfuseAurora = new ec2.SecurityGroup(this, "SgLangfuseAurora", {
      vpc,
      securityGroupName: `langfuse-${envName}-aurora`,
      description: "Langfuse Aurora cluster - allow PostgreSQL from ECS tasks",
      allowAllOutbound: false,
    });

    const sgLangfuseEcs = new ec2.SecurityGroup(this, "SgLangfuseEcs", {
      vpc,
      securityGroupName: `langfuse-${envName}-ecs`,
      description: "Langfuse ECS tasks",
      allowAllOutbound: false,
    });
    // ECS → Aurora
    sgLangfuseEcs.addEgressRule(
      sgLangfuseAurora,
      ec2.Port.tcp(5432),
      "PostgreSQL to Langfuse Aurora",
    );
    // ECS → internet (HTTPS for container registry etc.)
    sgLangfuseEcs.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "HTTPS outbound",
    );

    // Aurora ingress from ECS
    sgLangfuseAurora.addIngressRule(
      sgLangfuseEcs,
      ec2.Port.tcp(5432),
      "PostgreSQL from Langfuse ECS",
    );

    const sgLangfuseAlb = new ec2.SecurityGroup(this, "SgLangfuseAlb", {
      vpc,
      securityGroupName: `langfuse-${envName}-alb`,
      description: "Langfuse internal ALB",
      allowAllOutbound: false,
    });
    // ALB ingress: HTTP and HTTPS from within the VPC CIDR (internal ALB, not internet-facing)
    sgLangfuseAlb.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(80),
      "HTTP from VPC CIDR",
    );
    sgLangfuseAlb.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      "HTTPS from VPC CIDR",
    );
    // ALB → ECS on port 3000
    sgLangfuseAlb.addEgressRule(
      sgLangfuseEcs,
      ec2.Port.tcp(3000),
      "Langfuse web port",
    );
    // ECS ingress from ALB
    sgLangfuseEcs.addIngressRule(
      sgLangfuseAlb,
      ec2.Port.tcp(3000),
      "From Langfuse ALB",
    );

    // ── Aurora Serverless v2 cluster for Langfuse ─────────────────────────────
    const langfuseSubnetGroup = new rds.SubnetGroup(
      this,
      "LangfuseSubnetGroup",
      {
        description: `Langfuse ${envName} Aurora subnet group`,
        vpc,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      },
    );

    const langfuseAuroraCluster = new rds.DatabaseCluster(
      this,
      "LangfuseAurora",
      {
        clusterIdentifier: `langfuse-${envName}`,
        engine: rds.DatabaseClusterEngine.auroraPostgres({
          version: rds.AuroraPostgresEngineVersion.VER_16_4,
        }),
        // minCapacity: 0.5 (not 0) — prevents full auto-pause so Aurora is
        // immediately reachable when ECS starts the Langfuse container.
        // With minCapacity: 0, Prisma's migrate-on-startup exits ("Exiting...")
        // before Aurora wakes up, triggering the ECS circuit breaker every time.
        serverlessV2MinCapacity: 0.5,
        serverlessV2MaxCapacity: 4,
        writer: rds.ClusterInstance.serverlessV2("writer", {
          publiclyAccessible: false,
        }),
        vpc,
        subnetGroup: langfuseSubnetGroup,
        securityGroups: [sgLangfuseAurora],
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
        storageEncrypted: true,
        // AWS managed key — no KMS stack cross-dep
        credentials: rds.Credentials.fromGeneratedSecret("langfuse", {
          secretName: `/lex-agents/${envName}/langfuse/db-master`,
          // Exclude URL-special chars so the password is safe to embed in a
          // postgresql:// URL without percent-encoding causing parse errors.
          excludeCharacters: " %+~`#$&*()|[]{}:;<>?!'/@\"\\=",
        }),
        defaultDatabaseName: "langfuse",
        iamAuthentication: false, // Langfuse uses password auth
        enableDataApi: false,
        backup: {
          retention: cdk.Duration.days(7),
        },
        cloudwatchLogsExports: ["postgresql"],
        cloudwatchLogsRetention: logs.RetentionDays.ONE_MONTH,
        deletionProtection: false,
        removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
        port: 5432,
      },
    );

    this.langfuseAurora = langfuseAuroraCluster;

    // ── Secrets ───────────────────────────────────────────────────────────────
    // Langfuse bootstrap secrets — generated as random strings by Secrets Manager.
    // Update values post-deploy if you need specific values; the generated strings
    // are cryptographically random and safe for initial deployment.
    const nextauthSecret = new secretsmanager.Secret(
      this,
      "LangfuseNextauthSecret",
      {
        secretName: `/lex-agents/${envName}/langfuse/nextauth-secret`,
        description: `Langfuse ${envName} NextAuth secret (32-byte random, generated by SM)`,
        generateSecretString: {
          passwordLength: 64,
          excludePunctuation: true,
        },
      },
    );

    const saltSecret = new secretsmanager.Secret(this, "LangfuseSaltSecret", {
      secretName: `/lex-agents/${envName}/langfuse/salt`,
      description: `Langfuse ${envName} salt (32-byte random, generated by SM)`,
      generateSecretString: {
        passwordLength: 64,
        excludePunctuation: true,
      },
    });

    const encryptionKeySecret = new secretsmanager.Secret(
      this,
      "LangfuseEncryptionKeySecret",
      {
        secretName: `/lex-agents/${envName}/langfuse/encryption-key`,
        description: `Langfuse ${envName} 256-bit encryption key (generated by SM)`,
        generateSecretString: {
          passwordLength: 64,
          // Langfuse v3 validates ENCRYPTION_KEY against /^[0-9a-f]+$/i (AES-256 hex).
          // CDK SecretStringGenerator has no allowedCharacters; use exclusions instead.
          // excludeUppercase + excludePunctuation + excludeCharacters('g-z') → 0-9 + a-f only.
          excludeUppercase: true,
          excludePunctuation: true,
          excludeCharacters: "ghijklmnopqrstuvwxyz",
        },
      },
    );

    // API keys — populated by operators post-deploy with real Langfuse public/secret keys.
    const apiKeysSecret = new secretsmanager.Secret(
      this,
      "LangfuseApiKeysSecret",
      {
        secretName: `/lex-agents/${envName}/langfuse/api-keys`,
        description: `Langfuse ${envName} API keys (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY) — populate post-deploy`,
        generateSecretString: {
          secretStringTemplate: JSON.stringify({
            LANGFUSE_PUBLIC_KEY: "REPLACE_ME",
            LANGFUSE_SECRET_KEY: "REPLACE_ME",
          }),
          generateStringKey: "_unused",
          excludeCharacters: '"@/',
        },
      },
    );
    this.langfuseApiKeysSecret = apiKeysSecret;

    // ── ECS Cluster (dedicated for Langfuse) ─────────────────────────────────
    const langfuseCluster = new ecs.Cluster(this, "LangfuseCluster", {
      clusterName: `langfuse-${envName}`,
      vpc,
      containerInsightsV2: ecs.ContainerInsights.ENABLED,
    });

    // ── IAM roles ─────────────────────────────────────────────────────────────
    const executionRole = new iam.Role(this, "LangfuseExecutionRole", {
      roleName: `langfuse-${envName}-ecs-execution`,
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
    });

    const taskRole = new iam.Role(this, "LangfuseTaskRole", {
      roleName: `langfuse-${envName}-ecs-task`,
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });

    // Execution role needs all secrets it will inject at task startup.
    // Task role gets Aurora master secret so Prisma can re-read creds at runtime.
    [nextauthSecret, saltSecret, encryptionKeySecret].forEach((s) => {
      s.grantRead(executionRole);
    });
    langfuseAuroraCluster.secret?.grantRead(executionRole);
    langfuseAuroraCluster.secret?.grantRead(taskRole);

    // ── CloudWatch log group ──────────────────────────────────────────────────
    const logGroup = new logs.LogGroup(this, "LangfuseLogGroup", {
      // Renamed from /lex-agents/${envName}/langfuse to avoid collision with the
      // orphaned log group retained by a prior rollback (RETAIN policy). The old
      // name stays in AWS but is no longer managed by this stack.
      logGroupName: `/lex-agents/${envName}/langfuse-web`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const logging = ecs.LogDriver.awsLogs({
      streamPrefix: `langfuse-${envName}`,
      logGroup,
    });

    // ── ECS Task Definition ───────────────────────────────────────────────────
    const langfuseTaskDef = new ecs.FargateTaskDefinition(
      this,
      "LangfuseWebTaskDef",
      {
        family: `langfuse-web-${envName}`,
        // 2 vCPU / 4 GiB: Langfuse self-hosting docs recommend ≥2 GiB;
        // first-boot Prisma migrations on Aurora Serverless v2 have been
        // observed to spike above 2 GiB, triggering OOM kills that look
        // identical to an immediate crash in the circuit-breaker logs.
        cpu: 2048,
        memoryLimitMiB: 4096,
        executionRole,
        taskRole,
      },
    );

    // Aurora master secret — contains username, password, host, port, dbname.
    // Injected into the container as individual fields (DB_USER, DB_PASS) so the
    // shell entrypoint wrapper can assemble DATABASE_URL at runtime without a
    // Lambda custom resource. Aurora password excludeCharacters covers all
    // URL-special chars so no percent-encoding is needed in the shell assembly.
    const dbMasterSecret = langfuseAuroraCluster.secret!;

    // ── Aurora readiness init container ──────────────────────────────────────
    // aurora-wait does a full authenticated psql connection (not just pg_isready)
    // so it catches: Aurora still initialising, langfuse DB not yet created,
    // RDS SSL handshake not ready, and wrong credentials.  Only when psql
    // succeeds does the circuit-breaker-sensitive langfuse container start.
    const auroraWaitContainer = langfuseTaskDef.addContainer("aurora-wait", {
      containerName: "aurora-wait",
      // postgres:16-alpine ships psql + pg_isready; ECR Public mirror avoids
      // Docker Hub rate limits and is reachable via the existing HTTPS egress rule.
      image: ecs.ContainerImage.fromRegistry(
        "public.ecr.aws/docker/library/postgres:16-alpine",
      ),
      command: [
        "sh",
        "-c",
        // Full psql connection check — verifies SSL, authentication, and that
        // the langfuse database exists (defaultDatabaseName creates it on Aurora
        // init, but RDS can take a few extra seconds to commit it).
        "until psql \"postgresql://$DB_USER:$DB_PASS@$AURORA_HOST:5432/langfuse?sslmode=require\" -c 'SELECT 1' -q 2>/dev/null; do " +
          "echo 'aurora-wait: not ready, sleeping 5s'; sleep 5; " +
          "done; echo 'aurora-wait: langfuse DB accepting authenticated connections'",
      ],
      environment: {
        AURORA_HOST: langfuseAuroraCluster.clusterEndpoint.hostname,
      },
      secrets: {
        DB_USER: ecs.Secret.fromSecretsManager(dbMasterSecret, "username"),
        DB_PASS: ecs.Secret.fromSecretsManager(dbMasterSecret, "password"),
      },
      essential: false,
      logging,
      cpu: 16,
      memoryReservationMiB: 64,
    });

    const langfuseContainer = langfuseTaskDef.addContainer("langfuse", {
      containerName: "langfuse",
      // v2: Langfuse v3 requires ClickHouse + Redis + S3 which are not yet
      // provisioned in this stack. Pin to v2 (Postgres-only) for the MVP.
      // Upgrade to v3 once those dependencies are added.
      image: ecs.ContainerImage.fromRegistry("ghcr.io/langfuse/langfuse:2"),
      logging,
      portMappings: [{ containerPort: 3000 }],
      // Shell wrapper assembles DATABASE_URL at container startup from the
      // DB_USER / DB_PASS / DB_HOST env vars injected by ECS secrets. This
      // eliminates the Lambda custom resource that previously assembled the URL
      // at deploy time — a pattern that caused ResourceInitializationError when
      // the custom resource secret was deleted during CFn rollbacks.
      // Aurora password excludeCharacters strips all URL-special chars so the
      // password is safe to interpolate directly without percent-encoding.
      entryPoint: ["sh", "-c"],
      command: [
        // Assemble DATABASE_URL at runtime from the per-field secrets so no
        // Lambda custom resource is needed (avoids ResourceInitializationError
        // on CFn rollbacks that delete custom-resource secrets).
        // find /app handles both standalone layouts:
        //   /app/server.js          (Langfuse v2 standalone build)
        //   /app/web/server.js      (monorepo-root standalone build)
        "set -eu; " +
          'export DATABASE_URL="postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/langfuse?sslmode=require"; ' +
          'export DIRECT_URL="$DATABASE_URL"; ' +
          "SERVER=$(find /app -name 'server.js' -maxdepth 3 2>/dev/null | head -1); " +
          'echo "aurora-ok DB_HOST=$DB_HOST SERVER=${SERVER:-not-found}"; ' +
          "exec node ${SERVER:-server.js}",
      ],
      environment: {
        NODE_ENV: "production",
        // HOSTNAME=0.0.0.0 ensures Next.js standalone server listens on all
        // interfaces (not just 127.0.0.1), making it reachable from the ALB.
        HOSTNAME: "0.0.0.0",
        PORT: "3000",
        LANGFUSE_ENABLE_EXPERIMENTAL_FEATURES: "false",
        TELEMETRY_ENABLED: "false",
        NEXTAUTH_URL: "http://localhost:3000",
        // DB_HOST resolved by CloudFormation from the Aurora cluster endpoint.
        DB_HOST: langfuseAuroraCluster.clusterEndpoint.hostname,
      },
      secrets: {
        // Inject individual fields from the Aurora master secret JSON so the
        // shell wrapper can assemble DATABASE_URL without a custom resource.
        DB_USER: ecs.Secret.fromSecretsManager(dbMasterSecret, "username"),
        DB_PASS: ecs.Secret.fromSecretsManager(dbMasterSecret, "password"),
        NEXTAUTH_SECRET: ecs.Secret.fromSecretsManager(nextauthSecret),
        SALT: ecs.Secret.fromSecretsManager(saltSecret),
        ENCRYPTION_KEY: ecs.Secret.fromSecretsManager(encryptionKeySecret),
      },
      healthCheck: {
        command: [
          "CMD-SHELL",
          "wget -qO- http://localhost:3000/api/public/health || exit 1",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        // startPeriod covers Prisma migration time on a fresh DB (can be 3-5 min).
        // aurora-wait guarantees Aurora is connectable before Langfuse starts,
        // so this budget is purely for migrations + app boot, not Aurora warm-up.
        // 10 retries × 30s = 300s extra after the start period.
        retries: 10,
        startPeriod: cdk.Duration.seconds(300),
      },
      readonlyRootFilesystem: false,
    });

    // Start langfuse only after aurora-wait confirms TCP connectivity to Aurora.
    langfuseContainer.addContainerDependencies({
      container: auroraWaitContainer,
      condition: ecs.ContainerDependencyCondition.SUCCESS,
    });

    // X-Ray sidecar
    langfuseTaskDef.addContainer("xray-daemon", {
      containerName: "xray-daemon",
      image: ecs.ContainerImage.fromRegistry(
        "public.ecr.aws/xray-daemon/aws-xray-daemon:3.x",
      ),
      logging,
      portMappings: [{ containerPort: 2000, protocol: ecs.Protocol.UDP }],
      essential: false,
      cpu: 32,
      memoryReservationMiB: 64,
    });

    // ── ECS Service ───────────────────────────────────────────────────────────
    const langfuseService = new ecs.FargateService(this, "LangfuseWebService", {
      serviceName: `langfuse-web-${envName}`,
      cluster: langfuseCluster,
      taskDefinition: langfuseTaskDef,
      desiredCount: 1,
      securityGroups: [sgLangfuseEcs],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      platformVersion: ecs.FargatePlatformVersion.LATEST,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 0,
      maxHealthyPercent: 200,
    });
    // Suppress unused variable
    void langfuseService;

    // ── Application Load Balancer (internal) ──────────────────────────────────
    const alb = new elbv2.ApplicationLoadBalancer(this, "LangfuseAlb", {
      loadBalancerName: `langfuse-${envName}`,
      vpc,
      internetFacing: false,
      securityGroup: sgLangfuseAlb,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });
    // Explicitly destroy ALB on stack deletion so rollbacks don't leave
    // orphaned load balancers that block future CREATE attempts.
    alb.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    this.langfuseUrl = alb.loadBalancerDnsName;

    // Target group for langfuse-web
    const langfuseTg = new elbv2.ApplicationTargetGroup(this, "LangfuseTg", {
      targetGroupName: `langfuse-${envName}-web`,
      vpc,
      port: 3000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [
        langfuseService.loadBalancerTarget({
          containerName: "langfuse",
          containerPort: 3000,
        }),
      ],
      healthCheck: {
        path: "/api/public/health",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // HTTP listener (port 80) — always present for VPC-internal Langfuse SDK calls.
    // The API container uses http://<alb-dns> as LANGFUSE_HOST in environments
    // without an ACM certificate. HTTPS listener is added below when cert is provided.
    alb.addListener("LangfuseHttpListener", {
      port: 80,
      open: false,
      defaultAction: elbv2.ListenerAction.forward([langfuseTg]),
    });

    // Optional HTTPS listener — use ACM cert from context if provided
    const langfuseAcmCertArn = this.node.tryGetContext(
      "lexAgents:langfuseAcmCertArn",
    ) as string | undefined;

    // Require ACM cert in production; skip HTTPS listener when not provided
    // (e.g. local synth / CI without cert context). Langfuse is VPC-internal.
    if (!langfuseAcmCertArn) {
      cdk.Annotations.of(this).addWarning(
        "lexAgents:langfuseAcmCertArn not set — HTTPS listener will NOT be created. " +
          "Provide an ACM certificate ARN to enable TLS.",
      );
    }
    const cert = langfuseAcmCertArn
      ? acm.Certificate.fromCertificateArn(
          this,
          "LangfuseCert",
          langfuseAcmCertArn,
        )
      : undefined;
    if (cert) {
      alb.addListener("LangfuseHttpsListener", {
        port: 443,
        open: false,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        certificates: [cert],
        defaultAction: elbv2.ListenerAction.forward([langfuseTg]),
      });
    }

    // ── CfnOutputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "LangfuseInternalUrl", {
      value: alb.loadBalancerDnsName,
      exportName: `${id}-LangfuseInternalUrl`,
      description: "Langfuse internal ALB DNS name (VPC-only)",
    });

    new cdk.CfnOutput(this, "LangfuseClusterArn", {
      value: langfuseCluster.clusterArn,
      exportName: `${id}-LangfuseClusterArn`,
      description: "Langfuse ECS cluster ARN",
    });

    new cdk.CfnOutput(this, "LangfuseAuroraEndpoint", {
      value: langfuseAuroraCluster.clusterEndpoint.socketAddress,
      exportName: `${id}-LangfuseAuroraEndpoint`,
      description: "Langfuse Aurora writer endpoint (host:port)",
    });

    // ── cdk-nag suppressions ───────────────────────────────────────────────────
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-ECS2",
        reason:
          "Langfuse image pulled from ghcr.io (not ECR private). aurora-wait uses ECR Public mirror (public.ecr.aws). No ECR private alternative for official Langfuse v2 image.",
      },
      {
        id: "AwsSolutions-EC23",
        reason:
          "ALB listener without custom ACM cert in dev. Set lexAgents:langfuseAcmCertArn context key to enable TLS.",
      },
      {
        id: "HIPAA.Security-ECSTaskDefinitionUserForHostMode",
        reason:
          "Langfuse container runs as default user (non-root enforcement is upstream responsibility of the ghcr.io image).",
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "ECS task role wildcard permissions scoped to minimum required for CloudWatch Logs and X-Ray.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AmazonECSTaskExecutionRolePolicy is AWS-recommended for ECS task execution.",
      },
      {
        id: "AwsSolutions-RDS10",
        reason: "Deletion protection disabled for dev Langfuse Aurora cluster.",
      },
      {
        id: "AwsSolutions-RDS6",
        reason:
          "Langfuse uses password auth (not IAM) — iamAuthentication: false is intentional.",
      },
      {
        id: "AwsSolutions-RDS16",
        reason:
          "PostgreSQL logs exported to CloudWatch via cloudwatchLogsExports.",
      },
      {
        id: "AwsSolutions-ELB2",
        reason:
          "ALB access logs not required for internal Langfuse ALB in dev.",
      },
      {
        id: "AwsSolutions-ECS4",
        reason: "Container Insights enabled at cluster level.",
      },
      {
        id: "AwsSolutions-ECS7",
        reason:
          "Container Insights not required per container in dev; cluster-level insight is sufficient.",
      },
      {
        id: "AwsSolutions-SMG4",
        reason:
          "Langfuse secrets (nextauth, salt, encryption-key) are manually populated; no automated rotation in dev.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "Langfuse log group in dev; KMS encryption added in staging/prod.",
      },
      {
        id: "HIPAA.Security-SecretsManagerRotationEnabled",
        reason:
          "Langfuse infrastructure secrets are static — rotation managed manually per ADR 0050.",
      },
      {
        id: "HIPAA.Security-SecretsManagerUsingKMSKey",
        reason:
          "Langfuse secrets use AWS managed KMS in dev; CMK added in prod.",
      },
      {
        id: "HIPAA.Security-RDSLoggingEnabled",
        reason:
          "Aurora PostgreSQL cloudwatchLogsExports includes postgresql log.",
      },
      {
        id: "HIPAA.Security-RDSInstanceBackupEnabled",
        reason: "Aurora cluster backup retention = 7 days with PITR active.",
      },
      {
        id: "HIPAA.Security-RDSInstanceDeletionProtectionEnabled",
        reason:
          "Deletion protection disabled intentionally for dev Langfuse cluster.",
      },
      {
        id: "HIPAA.Security-RDSMultiAZSupport",
        reason:
          "Aurora Serverless v2 writer provides equivalent resilience in dev.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline policies on ECS roles are CDK-generated minimal-scope policies.",
      },
      {
        id: "HIPAA.Security-ALBHttpDropInvalidHeaderEnabled",
        reason: "Dev internal ALB; enable in production.",
      },
      {
        id: "HIPAA.Security-ELBDeletionProtectionEnabled",
        reason: "Dev internal ALB; enable in production.",
      },
      {
        id: "HIPAA.Security-ELBLoggingEnabled",
        reason: "Dev internal ALB; access logs not required.",
      },
      {
        id: "HIPAA.Security-ALBHttpToHttpsRedirection",
        reason: "Dev: no domain/cert; HTTPS redirect with ACM in production.",
      },
      {
        id: "HIPAA.Security-ELBv2ACMCertificateRequired",
        reason:
          "Dev: no ACM cert; provide lexAgents:langfuseAcmCertArn for HTTPS.",
      },
    ]);

    // ── Aurora writer instance suppressions ───────────────────────────────────
    const langfuseWriterNode = langfuseAuroraCluster.node.findChild("writer");
    NagSuppressions.addResourceSuppressions(
      langfuseWriterNode,
      [
        {
          id: "HIPAA.Security-RDSEnhancedMonitoringEnabled",
          reason: "Enhanced monitoring skipped in dev to reduce cost.",
        },
        {
          id: "HIPAA.Security-RDSInBackupPlan",
          reason:
            "Aurora dev cluster not in AWS Backup plan — cost optimization for dev.",
        },
      ],
      true,
    );
  }
}
