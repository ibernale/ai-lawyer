/**
 * AppServicesStack
 *
 * Deploys the lex-agents application on ECS Fargate:
 *   - EFS filesystem for Qdrant storage and HuggingFace model cache
 *   - Secrets Manager secret for runtime env vars (ANTHROPIC_API_KEY, etc.)
 *   - ECS Cluster with Container Insights
 *   - Application Load Balancer (HTTP/80; HTTPS/443 enabled when
 *     context key lexAgents:acmCertArn is present)
 *   - Three Fargate services: qdrant, api, web
 *   - Application Auto Scaling on API service (70% CPU target, 1–4 tasks)
 *   - DB_SECRET_ARN env var + grantRead so app builds DSN at startup
 *   - Aurora IAM auth grant (grantConnect) for app_user
 *
 * After deploy, populate the secret:
 *   aws secretsmanager put-secret-value \
 *     --secret-id lex-agents/dev/env \
 *     --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-...","ENVIRONMENT":"demo"}'
 */

import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as logs from "aws-cdk-lib/aws-logs";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as iam from "aws-cdk-lib/aws-iam";
import * as appscaling from "aws-cdk-lib/aws-applicationautoscaling";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import { NetworkSpokeStack } from "./network-spoke";
import { AppEcrStack } from "./app-ecr";
import type { DataStack } from "./data";
import type { LangfuseStack } from "./langfuse";

export interface AppServicesStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
  ecrStack: AppEcrStack;
  /** DataStack — required from Fase 9.2 onwards. */
  dataStack: DataStack;
  /** LangfuseStack — optional; when provided, injects Langfuse API keys into the API container. */
  langfuseStack?: LangfuseStack;
}

export class AppServicesStack extends cdk.Stack {
  public readonly alb: elbv2.ApplicationLoadBalancer;
  public readonly cluster: ecs.Cluster;

  constructor(scope: Construct, id: string, props: AppServicesStackProps) {
    super(scope, id, props);
    const { envName, networkStack, ecrStack, dataStack, langfuseStack } = props;
    const vpc = networkStack.vpc;

    // Image digests pin ECS task definitions to exact images (no :latest drift).
    // In CI, these come from --context flags set after docker/build-push-action.
    // Locally, a placeholder is used so cdk synth works without building images.
    const imageDigestApi =
      (this.node.tryGetContext("imageDigestApi") as string | undefined) ??
      "sha256:0000000000000000000000000000000000000000000000000000000000000000";
    const imageDigestWeb =
      (this.node.tryGetContext("imageDigestWeb") as string | undefined) ??
      "sha256:0000000000000000000000000000000000000000000000000000000000000000";

    // ── CloudWatch log group ───────────────────────────────────────────────
    const logGroup = new logs.LogGroup(this, "AppLogGroup", {
      logGroupName: `/lex-agents/${envName}/ecs`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── Secrets Manager — runtime env vars ───────────────────────────────
    // Populate after deploy:
    //   aws secretsmanager put-secret-value \
    //     --secret-id lex-agents/dev/env \
    //     --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-..."}'
    const appSecret = new secretsmanager.Secret(this, "AppSecret", {
      secretName: `lex-agents/${envName}/env`,
      description: "Runtime environment variables for lex-agents services",
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          ANTHROPIC_API_KEY: "REPLACE_ME",
          VOYAGE_API_KEY: "REPLACE_ME",
          ENVIRONMENT: envName,
          LOG_LEVEL: "INFO",
        }),
        generateStringKey: "_unused",
        excludeCharacters: '"@/',
      },
    });

    // ── EFS filesystem — persistent storage ───────────────────────────────
    const sgEfs = new ec2.SecurityGroup(this, "SgEfs", {
      vpc,
      securityGroupName: `lex-agents-${envName}-efs`,
      description: "EFS mount target - allow NFS from private subnets",
      allowAllOutbound: false,
    });

    const fileSystem = new efs.FileSystem(this, "AppEfs", {
      vpc,
      fileSystemName: `lex-agents-${envName}`,
      encrypted: true,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      throughputMode: efs.ThroughputMode.BURSTING,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_14_DAYS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      securityGroup: sgEfs,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    // EFS access points
    const qdrantAp = fileSystem.addAccessPoint("QdrantAp", {
      path: "/qdrant",
      createAcl: { ownerGid: "1000", ownerUid: "1000", permissions: "755" },
      posixUser: { gid: "1000", uid: "1000" },
    });

    const dataAp = fileSystem.addAccessPoint("DataAp", {
      path: "/data",
      createAcl: { ownerGid: "1000", ownerUid: "1000", permissions: "755" },
      posixUser: { gid: "1000", uid: "1000" },
    });

    const hfCacheAp = fileSystem.addAccessPoint("HfCacheAp", {
      path: "/hf-cache",
      createAcl: { ownerGid: "1000", ownerUid: "1000", permissions: "755" },
      posixUser: { gid: "1000", uid: "1000" },
    });

    // ── ECS cluster ────────────────────────────────────────────────────────
    this.cluster = new ecs.Cluster(this, "Cluster", {
      clusterName: `lex-agents-${envName}`,
      vpc,
      containerInsights: true,
      enableFargateCapacityProviders: true,
    });

    // ── IAM task execution role ────────────────────────────────────────────
    const executionRole = new iam.Role(this, "EcsExecutionRole", {
      roleName: `lex-agents-${envName}-ecs-execution`,
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
    });
    appSecret.grantRead(executionRole);
    // Explicit grants required because we use fromRegistry (not fromEcrRepository)
    // so CDK does not auto-grant ECR pull to the execution role.
    ecrStack.apiRepo.grantPull(executionRole);
    ecrStack.webRepo.grantPull(executionRole);
    langfuseStack?.langfuseApiKeysSecret.grantRead(executionRole);

    // ── IAM task role (runtime permissions) ───────────────────────────────
    const taskRole = new iam.Role(this, "EcsTaskRole", {
      roleName: `lex-agents-${envName}-ecs-task`,
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });
    appSecret.grantRead(taskRole);
    logGroup.grantWrite(taskRole);

    // ECS Exec requires ssmmessages permissions on the task role
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcsExecSsm",
        actions: [
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
        ],
        resources: ["*"],
      }),
    );

    // ── DB secret access — app reads secret at startup to build DSN ───────
    // The DataStack dbAppUserSecret holds {"username":"lex_app","password":"..."}
    // DB_SECRET_ARN is injected as a plain env var; the app fetches the secret
    // via lex_agents_shared.secrets at startup and assembles the DSN.
    //
    // NOTE: We use explicit identity-policy grants instead of grantRead() to
    // avoid a CDK cross-stack dependency cycle:
    //   AppServices → (grantRead) → Data.dbAppUserSecret (secretsKey in KmsStack)
    //   → KMS resource policy → AppServices/EcsTaskRole → cycle!
    // Same pattern used above for rds-connect.
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DbSecretRead",
        actions: [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ],
        resources: [dataStack.dbAppUserSecret.secretArn],
      }),
    );
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DbSecretKmsDecrypt",
        actions: ["kms:Decrypt", "kms:DescribeKey"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `secretsmanager.${this.region}.amazonaws.com`,
          },
        },
      }),
    );

    // Aurora IAM authentication — add rds-connect permission directly to avoid
    // cross-stack cyclic reference that aurora.grantConnect() would introduce
    // (DataStack already depends on NetworkSpokeStack; grantConnect resolves the
    // cluster ARN via the endpoint, which creates a reverse dependency cycle).
    taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["rds-db:connect"],
        // Wildcard on DB user — constrained to this account/region via condition
        resources: [
          `arn:aws:rds-db:${this.region}:${this.account}:dbuser:*/app_user`,
        ],
      }),
    );

    // ── Security group — ECS tasks → EFS ──────────────────────────────────
    const sgEcsTask = new ec2.SecurityGroup(this, "SgEcsTask", {
      vpc,
      securityGroupName: `lex-agents-${envName}-ecs-task`,
      description: "ECS tasks - allow outbound to EFS and internet via NAT",
      allowAllOutbound: true,
    });
    sgEfs.addIngressRule(sgEcsTask, ec2.Port.tcp(2049), "NFS from ECS tasks");

    // ── ALB security group — HTTP/HTTPS from internet (demo) ──────────────
    const sgAlbDemo = new ec2.SecurityGroup(this, "SgAlbDemo", {
      vpc,
      securityGroupName: `lex-agents-${envName}-alb-demo`,
      description: "ALB demo - HTTP from internet",
      allowAllOutbound: true,
    });
    sgAlbDemo.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(80),
      "HTTP from internet",
    );
    sgAlbDemo.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "HTTPS from internet",
    );

    // ── Application Load Balancer ──────────────────────────────────────────
    this.alb = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      loadBalancerName: `lex-agents-${envName}`,
      vpc,
      internetFacing: true,
      securityGroup: sgAlbDemo,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });

    const httpListener = this.alb.addListener("HttpListener", {
      port: 80,
      open: false,
      defaultAction: elbv2.ListenerAction.fixedResponse(404, {
        contentType: "text/plain",
        messageBody: "Not found",
      }),
    });

    // ── Optional HTTPS listener (443) ─────────────────────────────────────
    // Requires context key: lexAgents:acmCertArn
    // Example: cdk deploy --context lexAgents:acmCertArn=arn:aws:acm:...
    // Without the context key the HTTPS listener is skipped and a warning
    // is emitted. Wire in a real ACM certificate before production use.
    const acmCertArn = this.node.tryGetContext("lexAgents:acmCertArn") as
      | string
      | undefined;
    if (acmCertArn) {
      const cert = acm.Certificate.fromCertificateArn(
        this,
        "AlbCert",
        acmCertArn,
      );
      const httpsListener = this.alb.addListener("HttpsListener", {
        port: 443,
        open: false,
        protocol: elbv2.ApplicationProtocol.HTTPS,
        sslPolicy: elbv2.SslPolicy.TLS13_RES,
        certificates: [cert],
        defaultAction: elbv2.ListenerAction.fixedResponse(404, {
          contentType: "text/plain",
          messageBody: "Not found",
        }),
      });

      // Redirect HTTP → HTTPS when cert is available
      httpListener.addAction("HttpToHttpsRedirect", {
        priority: 1,
        conditions: [elbv2.ListenerCondition.pathPatterns(["/*"])],
        action: elbv2.ListenerAction.redirect({
          protocol: "HTTPS",
          port: "443",
          permanent: true,
        }),
      });

      // Expose httpsListener so subclasses / tests can reference it
      new cdk.CfnOutput(this, "HttpsListenerArn", {
        value: httpsListener.listenerArn,
        exportName: `${id}-HttpsListenerArn`,
        description: "ALB HTTPS listener ARN",
      });
    } else {
      // Print a warning at synth time; not a hard error in dev.
      // TODO: provide lexAgents:acmCertArn context key for HTTPS.
      process.stderr.write(
        `[AppServicesStack] WARNING: context key 'lexAgents:acmCertArn' is not set. ` +
          `HTTPS listener (port 443) will NOT be created. ` +
          `Pass --context lexAgents:acmCertArn=<arn> to enable TLS.\n`,
      );
    }

    // ── Helper: logging config ─────────────────────────────────────────────
    const logging = ecs.LogDriver.awsLogs({
      streamPrefix: `lex-agents-${envName}`,
      logGroup,
    });

    // ══════════════════════════════════════════════════════════════════════
    // Qdrant service
    // ══════════════════════════════════════════════════════════════════════

    const qdrantTaskDef = new ecs.FargateTaskDefinition(this, "QdrantTaskDef", {
      family: `lex-agents-${envName}-qdrant`,
      cpu: 512,
      memoryLimitMiB: 1024,
      executionRole,
      taskRole,
      volumes: [
        {
          name: "qdrant-storage",
          efsVolumeConfiguration: {
            fileSystemId: fileSystem.fileSystemId,
            transitEncryption: "ENABLED",
            authorizationConfig: {
              accessPointId: qdrantAp.accessPointId,
              iam: "ENABLED",
            },
          },
        },
      ],
    });

    const qdrantContainer = qdrantTaskDef.addContainer("qdrant", {
      image: ecs.ContainerImage.fromRegistry("qdrant/qdrant:v1.18.0"),
      logging,
      portMappings: [{ containerPort: 6333 }, { containerPort: 6334 }],
      healthCheck: {
        command: [
          "CMD-SHELL",
          'bash -c "echo > /dev/tcp/localhost/6333" || exit 1',
        ],
        interval: cdk.Duration.seconds(10),
        timeout: cdk.Duration.seconds(5),
        retries: 5,
        startPeriod: cdk.Duration.seconds(15),
      },
      readonlyRootFilesystem: false,
    });

    qdrantContainer.addMountPoints({
      containerPath: "/qdrant/storage",
      sourceVolume: "qdrant-storage",
      readOnly: false,
    });

    const sgQdrant = new ec2.SecurityGroup(this, "SgQdrant", {
      vpc,
      securityGroupName: `lex-agents-${envName}-qdrant`,
      description: "Qdrant service - allow gRPC and REST from API tasks",
      allowAllOutbound: false,
    });
    sgEfs.addIngressRule(sgQdrant, ec2.Port.tcp(2049), "NFS from Qdrant");
    sgQdrant.addEgressRule(sgEfs, ec2.Port.tcp(2049), "NFS to EFS");

    const qdrantService = new ecs.FargateService(this, "QdrantService", {
      serviceName: `lex-agents-${envName}-qdrant`,
      cluster: this.cluster,
      taskDefinition: qdrantTaskDef,
      desiredCount: 1,
      securityGroups: [sgQdrant],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      platformVersion: ecs.FargatePlatformVersion.LATEST,
      enableExecuteCommand: true,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 0,
      maxHealthyPercent: 200,
    });

    fileSystem.grantRootAccess(qdrantService.taskDefinition.taskRole);
    fileSystem.connections.allowDefaultPortFrom(qdrantService.connections);

    // Qdrant is internal-only — no ALB target group needed.
    // The API service connects to it via Cloud Map: qdrant.lex-agents.local:6333

    // ══════════════════════════════════════════════════════════════════════
    // API service (FastAPI)
    // ══════════════════════════════════════════════════════════════════════

    const apiTaskDef = new ecs.FargateTaskDefinition(this, "ApiTaskDef", {
      family: `lex-agents-${envName}-api`,
      cpu: 512,
      memoryLimitMiB: 1024,
      executionRole,
      taskRole,
      volumes: [
        {
          name: "app-data",
          efsVolumeConfiguration: {
            fileSystemId: fileSystem.fileSystemId,
            transitEncryption: "ENABLED",
            authorizationConfig: {
              accessPointId: dataAp.accessPointId,
              iam: "ENABLED",
            },
          },
        },
        {
          name: "hf-cache",
          efsVolumeConfiguration: {
            fileSystemId: fileSystem.fileSystemId,
            transitEncryption: "ENABLED",
            authorizationConfig: {
              accessPointId: hfCacheAp.accessPointId,
              iam: "ENABLED",
            },
          },
        },
      ],
    });

    const apiContainer = apiTaskDef.addContainer("api", {
      image: ecs.ContainerImage.fromRegistry(
        `${ecrStack.apiRepo.repositoryUri}@${imageDigestApi}`,
      ),
      logging,
      portMappings: [{ containerPort: 8000 }],
      secrets: {
        ANTHROPIC_API_KEY: ecs.Secret.fromSecretsManager(
          appSecret,
          "ANTHROPIC_API_KEY",
        ),
        VOYAGE_API_KEY: ecs.Secret.fromSecretsManager(
          appSecret,
          "VOYAGE_API_KEY",
        ),
        ENVIRONMENT: ecs.Secret.fromSecretsManager(appSecret, "ENVIRONMENT"),
        LOG_LEVEL: ecs.Secret.fromSecretsManager(appSecret, "LOG_LEVEL"),
        // JSON array of users; set via Secrets Manager so the hash is never in git.
        // Generate hash: python3 -c "import bcrypt; print(bcrypt.hashpw(b'pw', bcrypt.gensalt(12)).decode())"
        AUTH_USERS_JSON: ecs.Secret.fromSecretsManager(
          appSecret,
          "AUTH_USERS_JSON",
        ),
        // Langfuse API keys — injected when LangfuseStack is deployed (Fase 11).
        // Populate the secret post-deploy:
        //   aws secretsmanager put-secret-value \
        //     --secret-id /lex-agents/{env}/langfuse/api-keys \
        //     --secret-string '{"LANGFUSE_PUBLIC_KEY":"pk-lf-...","LANGFUSE_SECRET_KEY":"sk-lf-..."}'
        ...(langfuseStack
          ? {
              LANGFUSE_PUBLIC_KEY: ecs.Secret.fromSecretsManager(
                langfuseStack.langfuseApiKeysSecret,
                "LANGFUSE_PUBLIC_KEY",
              ),
              LANGFUSE_SECRET_KEY: ecs.Secret.fromSecretsManager(
                langfuseStack.langfuseApiKeysSecret,
                "LANGFUSE_SECRET_KEY",
              ),
            }
          : {}),
      },
      environment: {
        QDRANT_URL: "http://qdrant.lex-agents.local:6333",
        DATA_DIR: "/app/data",
        HF_HOME: "/home/appuser/.cache/huggingface",
        // Plain ARN — the app resolves it via lex_agents_shared.secrets at startup.
        // The actual DB credentials (host, user, password) are never baked into the
        // task definition; they are fetched from Secrets Manager at runtime.
        DB_SECRET_ARN: dataStack.dbAppUserSecret.secretArn,
        // Aurora writer endpoint — used by the app to build the DSN.
        DB_HOST: dataStack.aurora.clusterEndpoint.hostname,
        // Aurora PostgreSQL always listens on port 5432; using a literal avoids
        // a cross-stack token dependency that would create a cyclic reference
        // between NetworkSpokeStack and DataStack at synthesis time.
        DB_PORT: "5432",
        DB_NAME: "lex_agents",
        // Langfuse internal ALB — SDK reads LANGFUSE_HOST automatically.
        ...(langfuseStack
          ? { LANGFUSE_HOST: `http://${langfuseStack.langfuseUrl}` }
          : {}),
      },
      healthCheck: {
        command: [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1",
        ],
        interval: cdk.Duration.seconds(20),
        timeout: cdk.Duration.seconds(5),
        retries: 5,
        startPeriod: cdk.Duration.seconds(30),
      },
      readonlyRootFilesystem: false,
    });

    apiContainer.addMountPoints(
      { containerPath: "/app/data", sourceVolume: "app-data", readOnly: false },
      {
        containerPath: "/home/appuser/.cache/huggingface",
        sourceVolume: "hf-cache",
        readOnly: false,
      },
    );

    const sgApi = new ec2.SecurityGroup(this, "SgApi", {
      vpc,
      securityGroupName: `lex-agents-${envName}-api-fargate`,
      description: "API Fargate tasks - ingress from ALB on 8000",
      allowAllOutbound: true,
    });
    sgApi.addIngressRule(sgAlbDemo, ec2.Port.tcp(8000), "API from ALB");
    sgQdrant.addIngressRule(sgApi, ec2.Port.tcp(6333), "Qdrant REST from API");
    sgQdrant.addIngressRule(sgApi, ec2.Port.tcp(6334), "Qdrant gRPC from API");
    sgQdrant.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "HTTPS egress for ECS agent",
    );

    // Allow API tasks to reach Aurora on 5432.
    // We use CfnSecurityGroupIngress (owned by THIS stack) rather than calling
    // sgAurora.addIngressRule() (which would mutate a foreign-stack SG and
    // create a cross-stack dependency cycle in test synthesis).
    new ec2.CfnSecurityGroupIngress(this, "AuroraSgiFromApi", {
      groupId: dataStack.sgAurora.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 5432,
      toPort: 5432,
      sourceSecurityGroupId: sgApi.securityGroupId,
      description: "Aurora from API",
    });

    const apiService = new ecs.FargateService(this, "ApiService", {
      serviceName: `lex-agents-${envName}-api`,
      cluster: this.cluster,
      taskDefinition: apiTaskDef,
      desiredCount: 1,
      securityGroups: [sgApi],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      platformVersion: ecs.FargatePlatformVersion.LATEST,
      enableExecuteCommand: true,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 0,
      maxHealthyPercent: 200,
      capacityProviderStrategies: [
        { capacityProvider: "FARGATE", base: 1, weight: 1 },
        { capacityProvider: "FARGATE_SPOT", base: 0, weight: 3 },
      ],
    });

    fileSystem.grantRootAccess(apiService.taskDefinition.taskRole);
    fileSystem.connections.allowDefaultPortFrom(apiService.connections);

    // ── Application Auto Scaling — API service ─────────────────────────────
    // Target 70% CPU; scale between 1 and 4 tasks.
    const apiScalableTarget = new appscaling.ScalableTarget(
      this,
      "ApiScalableTarget",
      {
        serviceNamespace: appscaling.ServiceNamespace.ECS,
        resourceId: `service/${this.cluster.clusterName}/${apiService.serviceName}`,
        scalableDimension: "ecs:service:DesiredCount",
        minCapacity: 1,
        maxCapacity: 4,
      },
    );

    new appscaling.TargetTrackingScalingPolicy(this, "ApiCpuScaling", {
      scalingTarget: apiScalableTarget,
      targetValue: 70,
      predefinedMetric:
        appscaling.PredefinedMetric.ECS_SERVICE_AVERAGE_CPU_UTILIZATION,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(30),
    });

    const apiTg = new elbv2.ApplicationTargetGroup(this, "ApiTg", {
      targetGroupName: `lex-agents-${envName}-api`,
      vpc,
      port: 8000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [
        apiService.loadBalancerTarget({
          containerName: "api",
          containerPort: 8000,
        }),
      ],
      healthCheck: {
        path: "/health",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // ══════════════════════════════════════════════════════════════════════
    // Web service (Next.js)
    // ══════════════════════════════════════════════════════════════════════

    const webTaskDef = new ecs.FargateTaskDefinition(this, "WebTaskDef", {
      family: `lex-agents-${envName}-web`,
      cpu: 256,
      memoryLimitMiB: 512,
      executionRole,
      taskRole,
    });

    webTaskDef.addContainer("web", {
      image: ecs.ContainerImage.fromRegistry(
        `${ecrStack.webRepo.repositoryUri}@${imageDigestWeb}`,
      ),
      logging,
      portMappings: [{ containerPort: 3000 }],
      environment: {
        // Server-side (SSR) calls — goes through the ALB from within the VPC
        API_BASE_URL: `http://${this.alb.loadBalancerDnsName}`,
        // Client-side calls also use the public ALB (NEXT_PUBLIC baked at build-time;
        // browser-side components use relative paths via Next.js rewrites instead)
        NEXT_PUBLIC_API_URL: `http://${this.alb.loadBalancerDnsName}`,
        NODE_ENV: "production",
        // Langfuse iframe URL for the LLM traces admin panel (Fase 11).
        ...(langfuseStack
          ? { NEXT_PUBLIC_LANGFUSE_URL: `http://${langfuseStack.langfuseUrl}` }
          : {}),
      },
      healthCheck: {
        // The Dockerfile CMD forces HOSTNAME=0.0.0.0 so Next.js listens on all
        // interfaces — 127.0.0.1 is therefore reachable.
        command: [
          "CMD",
          "node",
          "-e",
          "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<400?0:1)).on('error',()=>process.exit(1))",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
      readonlyRootFilesystem: false,
    });

    const sgWeb = new ec2.SecurityGroup(this, "SgWeb", {
      vpc,
      securityGroupName: `lex-agents-${envName}-web-fargate`,
      description: "Web Fargate tasks - ingress from ALB on 3000",
      allowAllOutbound: true,
    });
    sgWeb.addIngressRule(sgAlbDemo, ec2.Port.tcp(3000), "Web from ALB");

    const webService = new ecs.FargateService(this, "WebService", {
      serviceName: `lex-agents-${envName}-web`,
      cluster: this.cluster,
      taskDefinition: webTaskDef,
      desiredCount: 1,
      securityGroups: [sgWeb],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      platformVersion: ecs.FargatePlatformVersion.LATEST,
      enableExecuteCommand: true,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 0,
      maxHealthyPercent: 200,
      capacityProviderStrategies: [
        { capacityProvider: "FARGATE", base: 1, weight: 1 },
        { capacityProvider: "FARGATE_SPOT", base: 0, weight: 3 },
      ],
    });

    const webTg = new elbv2.ApplicationTargetGroup(this, "WebTg", {
      targetGroupName: `lex-agents-${envName}-web`,
      vpc,
      port: 3000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [
        webService.loadBalancerTarget({
          containerName: "web",
          containerPort: 3000,
        }),
      ],
      healthCheck: {
        path: "/",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // ── ALB listener rules ─────────────────────────────────────────────────
    // FastAPI routes → API service (browser calls these directly; no Next.js rewrite needed)
    httpListener.addTargetGroups("ApiHealthRule", {
      priority: 15,
      conditions: [
        elbv2.ListenerCondition.pathPatterns(["/health", "/version"]),
      ],
      targetGroups: [apiTg],
    });
    httpListener.addTargetGroups("ApiAuthRule", {
      priority: 20,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/auth/*", "/auth"])],
      targetGroups: [apiTg],
    });
    httpListener.addTargetGroups("ApiV1Rule", {
      priority: 25,
      conditions: [
        elbv2.ListenerCondition.pathPatterns(["/api/v1/*", "/api/v1"]),
      ],
      targetGroups: [apiTg],
    });

    // /* (default) → Web service
    httpListener.addAction("WebDefault", {
      priority: 100,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/*"])],
      action: elbv2.ListenerAction.forward([webTg]),
    });

    // ── Cloud Map namespace for internal service discovery ─────────────────
    const namespace = this.cluster.addDefaultCloudMapNamespace({
      name: "lex-agents.local",
      vpc,
    });

    qdrantService.enableCloudMap({
      cloudMapNamespace: namespace,
      name: "qdrant",
    });

    // ── Outputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "AlbDnsName", {
      value: `http://${this.alb.loadBalancerDnsName}`,
      exportName: `${id}-AlbDnsName`,
      description: "Application Load Balancer URL (demo)",
    });

    new cdk.CfnOutput(this, "SecretArn", {
      value: appSecret.secretArn,
      exportName: `${id}-SecretArn`,
      description:
        "Secrets Manager ARN - populate ANTHROPIC_API_KEY before starting tasks",
    });

    new cdk.CfnOutput(this, "EfsId", {
      value: fileSystem.fileSystemId,
      exportName: `${id}-EfsId`,
      description: "EFS filesystem ID for persistent storage",
    });

    new cdk.CfnOutput(this, "DbSecretArn", {
      value: dataStack.dbAppUserSecret.secretArn,
      exportName: `${id}-DbSecretArn`,
      description: "Aurora app-user secret ARN (read by API at startup)",
    });

    // cdk-nag suppressions — demo environment, production hardening tracked in backlog
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-ELB2",
        reason: "ALB access logs post-demo; S3 bucket not provisioned.",
      },
      {
        id: "AwsSolutions-EC23",
        reason: "Demo ALB uses HTTP/80; upgrade to HTTPS+ACM in production.",
      },
      {
        id: "AwsSolutions-ECS2",
        reason: "Secrets Manager for sensitive values; safe env vars inline.",
      },
      {
        id: "AwsSolutions-ECS4",
        reason: "Container Insights enabled at cluster level.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason: "AmazonECSTaskExecutionRolePolicy is AWS-recommended for ECS.",
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "EFS grantRootAccess uses wildcard by design; scoped per filesystem. ssmmessages wildcard required for ECS Exec.",
      },
      {
        id: "AwsSolutions-SMG4",
        reason:
          "Secret rotation not needed for demo; add Lambda rotator in production.",
      },
      {
        id: "AwsSolutions-AS3",
        reason:
          "Step scaling notifications omitted for dev; CloudWatch alarms in ObservabilityStack.",
      },
      // HIPAA — acknowledged for demo; not a HIPAA-regulated environment
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason: "Demo: KMS log encryption post-demo enhancement.",
      },
      {
        id: "HIPAA.Security-SecretsManagerRotationEnabled",
        reason: "Demo: rotation not configured.",
      },
      {
        id: "HIPAA.Security-SecretsManagerUsingKMSKey",
        reason: "Demo: CMK encryption post-demo.",
      },
      {
        id: "HIPAA.Security-EFSInBackupPlan",
        reason: "Demo: AWS Backup plan post-demo.",
      },
      {
        id: "HIPAA.Security-ALBHttpDropInvalidHeaderEnabled",
        reason: "Demo ALB; enable in production.",
      },
      {
        id: "HIPAA.Security-ELBDeletionProtectionEnabled",
        reason: "Demo ALB; enable in production.",
      },
      {
        id: "HIPAA.Security-ELBLoggingEnabled",
        reason: "Demo: ALB access logs post-demo.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Demo: inline policies for simplicity; move to managed in production.",
      },
      {
        id: "HIPAA.Security-ALBHttpToHttpsRedirection",
        reason: "Demo HTTP only; HTTPS redirect with ACM in production.",
      },
      {
        id: "HIPAA.Security-ELBv2ACMCertificateRequired",
        reason: "Demo: no domain/cert; ACM certificate in production.",
      },
    ]);
  }
}
