/**
 * JaegerStack — Fase 11
 *
 * Deploys Jaeger all-in-one on ECS Fargate for distributed trace visualisation.
 * Uses in-memory storage (suitable for MVP / dev). For production with retention
 * requirements, swap to Cassandra or Elasticsearch backend.
 *
 * Architecture:
 *   - Internal ALB (VPC-only) with two listeners:
 *     - Port 80  → Jaeger UI  (container port 16686)
 *     - Port 4318 → OTLP HTTP (container port 4318)
 *   - ECS Fargate service: jaegertracing/all-in-one:1.76.0
 *
 * API containers export traces via OTLP HTTP to http://<alb-dns>:4318.
 * The admin web panel embeds the Jaeger UI via NEXT_PUBLIC_JAEGER_URL.
 *
 * Note: gRPC OTLP (port 4317) is intentionally NOT exposed through the ALB;
 * an ALB cannot efficiently proxy gRPC on non-standard ports. OTLP HTTP is
 * functionally equivalent and ALB-friendly.
 */

import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import type { NetworkSpokeStack } from "./network-spoke";

export interface JaegerStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
}

export class JaegerStack extends cdk.Stack {
  /** Internal ALB DNS name for Jaeger UI (VPC-only) — use as NEXT_PUBLIC_JAEGER_URL. */
  public readonly jaegerUiUrl: string;
  /** Internal ALB endpoint for OTLP HTTP traces — use as OTEL_EXPORTER_OTLP_ENDPOINT. */
  public readonly jaegerOtlpUrl: string;

  constructor(scope: Construct, id: string, props: JaegerStackProps) {
    super(scope, id, props);
    const { envName, networkStack } = props;
    const vpc = networkStack.vpc;

    // ── Security groups ───────────────────────────────────────────────────────

    const sgJaegerEcs = new ec2.SecurityGroup(this, "SgJaegerEcs", {
      vpc,
      securityGroupName: `jaeger-${envName}-ecs`,
      description: "Jaeger ECS tasks",
      allowAllOutbound: false,
    });
    // Allow HTTPS egress for pulling the container image from the public registry
    sgJaegerEcs.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "HTTPS outbound for image pull",
    );

    const sgJaegerAlb = new ec2.SecurityGroup(this, "SgJaegerAlb", {
      vpc,
      securityGroupName: `jaeger-${envName}-alb`,
      description: "Jaeger internal ALB - VPC-only ingress",
      allowAllOutbound: false,
    });
    // ALB ingress: UI and OTLP HTTP from within the VPC
    sgJaegerAlb.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(80),
      "Jaeger UI from VPC",
    );
    sgJaegerAlb.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(4318),
      "OTLP HTTP from VPC",
    );
    // ALB → ECS on Jaeger UI port
    sgJaegerAlb.addEgressRule(sgJaegerEcs, ec2.Port.tcp(16686), "Jaeger UI");
    // ALB → ECS on OTLP HTTP port
    sgJaegerAlb.addEgressRule(sgJaegerEcs, ec2.Port.tcp(4318), "OTLP HTTP");

    // ECS ingress from ALB
    sgJaegerEcs.addIngressRule(sgJaegerAlb, ec2.Port.tcp(16686), "UI from ALB");
    sgJaegerEcs.addIngressRule(
      sgJaegerAlb,
      ec2.Port.tcp(4318),
      "OTLP HTTP from ALB",
    );

    // ── CloudWatch log group ──────────────────────────────────────────────────
    const logGroup = new logs.LogGroup(this, "JaegerLogGroup", {
      logGroupName: `/lex-agents/${envName}/jaeger`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── ECS Cluster ───────────────────────────────────────────────────────────
    const jaegerCluster = new ecs.Cluster(this, "JaegerCluster", {
      clusterName: `jaeger-${envName}`,
      vpc,
      containerInsights: true,
    });

    // ── IAM roles ─────────────────────────────────────────────────────────────
    const executionRole = new iam.Role(this, "JaegerExecutionRole", {
      roleName: `jaeger-${envName}-ecs-execution`,
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy",
        ),
      ],
    });

    const taskRole = new iam.Role(this, "JaegerTaskRole", {
      roleName: `jaeger-${envName}-ecs-task`,
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });
    logGroup.grantWrite(taskRole);

    // ── Task definition ───────────────────────────────────────────────────────
    const jaegerTaskDef = new ecs.FargateTaskDefinition(this, "JaegerTaskDef", {
      family: `jaeger-${envName}`,
      cpu: 512,
      memoryLimitMiB: 1024,
      executionRole,
      taskRole,
    });

    const logging = ecs.LogDriver.awsLogs({
      streamPrefix: `jaeger-${envName}`,
      logGroup,
    });

    jaegerTaskDef.addContainer("jaeger", {
      containerName: "jaeger",
      // Pin to a specific digest in production to avoid :latest drift.
      // For dev, the tag is sufficient.
      image: ecs.ContainerImage.fromRegistry("jaegertracing/all-in-one:1.76.0"),
      logging,
      portMappings: [
        { containerPort: 16686 }, // Jaeger UI
        { containerPort: 4318 }, // OTLP HTTP receiver
        { containerPort: 4317 }, // OTLP gRPC receiver (VPC-internal, not exposed via ALB)
      ],
      environment: {
        COLLECTOR_OTLP_ENABLED: "true",
        // In-memory storage — traces are lost on task restart.
        // For production retention, set SPAN_STORAGE_TYPE=cassandra or elasticsearch.
        SPAN_STORAGE_TYPE: "memory",
        MEMORY_MAX_TRACES: "50000",
      },
      healthCheck: {
        command: [
          "CMD-SHELL",
          "wget -qO- http://localhost:14269/health || exit 1",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(30),
      },
      readonlyRootFilesystem: false,
    });

    // ── ECS Service ───────────────────────────────────────────────────────────
    const jaegerService = new ecs.FargateService(this, "JaegerService", {
      serviceName: `jaeger-${envName}`,
      cluster: jaegerCluster,
      taskDefinition: jaegerTaskDef,
      desiredCount: 1,
      securityGroups: [sgJaegerEcs],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      platformVersion: ecs.FargatePlatformVersion.LATEST,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 0,
      maxHealthyPercent: 200,
    });

    // ── Internal Application Load Balancer ────────────────────────────────────
    const alb = new elbv2.ApplicationLoadBalancer(this, "JaegerAlb", {
      loadBalancerName: `jaeger-${envName}`,
      vpc,
      internetFacing: false,
      securityGroup: sgJaegerAlb,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    this.jaegerUiUrl = alb.loadBalancerDnsName;
    this.jaegerOtlpUrl = alb.loadBalancerDnsName;

    // Target group — Jaeger UI (port 16686)
    const uiTg = new elbv2.ApplicationTargetGroup(this, "JaegerUiTg", {
      targetGroupName: `jaeger-${envName}-ui`,
      vpc,
      port: 16686,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [
        jaegerService.loadBalancerTarget({
          containerName: "jaeger",
          containerPort: 16686,
        }),
      ],
      healthCheck: {
        path: "/",
        port: "16686",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(15),
    });

    // Target group — OTLP HTTP (port 4318)
    const otlpTg = new elbv2.ApplicationTargetGroup(this, "JaegerOtlpTg", {
      targetGroupName: `jaeger-${envName}-otlp`,
      vpc,
      port: 4318,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [
        jaegerService.loadBalancerTarget({
          containerName: "jaeger",
          containerPort: 4318,
        }),
      ],
      healthCheck: {
        path: "/v1/traces",
        port: "4318",
        healthyHttpCodes: "200,405",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: cdk.Duration.seconds(15),
    });

    // Port 80 → Jaeger UI
    alb.addListener("JaegerUiListener", {
      port: 80,
      open: false,
      defaultAction: elbv2.ListenerAction.forward([uiTg]),
    });

    // Port 4318 → OTLP HTTP
    alb.addListener("JaegerOtlpListener", {
      port: 4318,
      open: false,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.forward([otlpTg]),
    });

    // ── Outputs ───────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "JaegerUiUrl", {
      value: `http://${alb.loadBalancerDnsName}`,
      exportName: `${id}-JaegerUiUrl`,
      description:
        "Jaeger UI internal URL (VPC-only) — use as NEXT_PUBLIC_JAEGER_URL",
    });

    new cdk.CfnOutput(this, "JaegerOtlpUrl", {
      value: `http://${alb.loadBalancerDnsName}:4318`,
      exportName: `${id}-JaegerOtlpUrl`,
      description:
        "Jaeger OTLP HTTP endpoint — use as OTEL_EXPORTER_OTLP_ENDPOINT",
    });

    new cdk.CfnOutput(this, "JaegerClusterArn", {
      value: jaegerCluster.clusterArn,
      exportName: `${id}-JaegerClusterArn`,
    });

    // ── cdk-nag suppressions ──────────────────────────────────────────────────
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-ECS2",
        reason:
          "Jaeger all-in-one has no secrets to inject; env vars are non-sensitive config.",
      },
      {
        id: "AwsSolutions-ELB2",
        reason:
          "Jaeger is VPC-internal only; access logs add cost with no security benefit here.",
      },
      {
        id: "AwsSolutions-EC23",
        reason:
          "Internal ALB SG allows VPC CIDR — acceptable for internal-only tracing backend.",
      },
      {
        id: "HIPAA.Security-ECSTaskDefinitionUserForHostMode",
        reason: "Jaeger all-in-one runs as its default non-root user.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "Jaeger trace logs are internal observability data with no PII/PHI; KMS encryption not required in dev.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AmazonECSTaskExecutionRolePolicy is the standard CDK-managed policy for ECS task execution; no custom policy needed.",
      },
      {
        id: "HIPAA.Security-ALBHttpDropInvalidHeaderEnabled",
        reason:
          "Jaeger ALB is VPC-internal only; invalid header dropping is not required for internal tracing traffic.",
      },
      {
        id: "HIPAA.Security-ELBDeletionProtectionEnabled",
        reason:
          "Dev environment internal ALB; deletion protection not required.",
      },
      {
        id: "HIPAA.Security-ELBLoggingEnabled",
        reason:
          "Jaeger is VPC-internal only; ALB access logs add cost with no security benefit for an internal tracing backend.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline policies on ECS execution/task roles are CDK-generated minimal grants (CloudWatch Logs, ECR pull); no user-managed inline policies.",
      },
      {
        id: "HIPAA.Security-ALBHttpToHttpsRedirection",
        reason:
          "Jaeger ALB is VPC-internal only and serves plain HTTP; HTTPS redirection is not applicable for an internal tracing endpoint.",
      },
      {
        id: "HIPAA.Security-ELBv2ACMCertificateRequired",
        reason:
          "Jaeger ALB serves VPC-internal traffic only; TLS termination at the ALB is not required for an internal tracing backend.",
      },
    ]);

    void jaegerService; // suppress CDK unused-construct lint
  }
}
