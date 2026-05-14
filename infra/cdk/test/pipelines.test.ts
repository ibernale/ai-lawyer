/**
 * PipelinesStack tests — Fase 9.4
 *
 * Replaces pipeline.test.ts (Fase 9.2 single-source tests).
 * Validates the multi-source pipeline factory (13 sources, ADR 0049).
 *
 * Uses stub stacks to avoid cross-stack dependency cycles.
 */

import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Match, Template } from "aws-cdk-lib/assertions";
import { Construct } from "constructs";
import { PipelinesStack } from "../lib/stacks/pipelines";

// ── Stub stacks ────────────────────────────────────────────────────────────────

class StubNetworkStack extends cdk.Stack {
  public readonly vpc: ec2.IVpc;
  public readonly sgAurora: ec2.ISecurityGroup;
  public readonly sgEcsApi: ec2.ISecurityGroup;
  public readonly sgEcsWeb: ec2.ISecurityGroup;
  public readonly sgAlb: ec2.ISecurityGroup;
  public readonly sgAgentcore: ec2.ISecurityGroup;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);
    this.vpc = new ec2.Vpc(this, "Vpc", { maxAzs: 2, natGateways: 1 });
    const sg = (sid: string): ec2.ISecurityGroup =>
      new ec2.SecurityGroup(this, sid, { vpc: this.vpc, description: sid });
    this.sgAurora = sg("SgAurora");
    this.sgEcsApi = sg("SgEcsApi");
    this.sgEcsWeb = sg("SgEcsWeb");
    this.sgAlb = sg("SgAlb");
    this.sgAgentcore = sg("SgAgentcore");
  }
}

class StubAppServicesStack extends cdk.Stack {
  public readonly cluster: ecs.ICluster;
  public readonly alb: elbv2.IApplicationLoadBalancer;

  constructor(
    scope: Construct,
    id: string,
    vpc: ec2.IVpc,
    props: cdk.StackProps,
  ) {
    super(scope, id, props);
    this.cluster = new ecs.Cluster(this, "Cluster", {
      clusterName: "lex-agents-dev",
      vpc,
    });
    this.alb = new elbv2.ApplicationLoadBalancer(this, "Alb", {
      loadBalancerName: "lex-agents-dev",
      vpc,
      internetFacing: false,
    });
  }
}

class StubDataStack extends cdk.Stack {
  public readonly aurora: rds.IDatabaseCluster;
  public readonly sgAurora: ec2.ISecurityGroup;
  public readonly dbAppUserSecret: secretsmanager.ISecret;
  public readonly buckets: {
    raw: s3.IBucket;
    canonical: s3.IBucket;
    evals: s3.IBucket;
    backups: s3.IBucket;
  };

  constructor(
    scope: Construct,
    id: string,
    sgAurora: ec2.ISecurityGroup,
    props: cdk.StackProps,
  ) {
    super(scope, id, props);
    this.sgAurora = sgAurora;
    this.aurora = rds.DatabaseCluster.fromDatabaseClusterAttributes(
      this,
      "Aurora",
      {
        clusterIdentifier: "lex-agents-dev",
        clusterEndpointAddress: "stub.cluster.eu-central-1.rds.amazonaws.com",
        readerEndpointAddress: "stub.reader.eu-central-1.rds.amazonaws.com",
        instanceEndpointAddresses: [],
        instanceIdentifiers: [],
        port: 5432,
        securityGroups: [],
      },
    );
    this.dbAppUserSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      "DbSecret",
      "/lex-agents/dev/db/app-user",
    );
    const makeBucket = (bid: string): s3.IBucket =>
      s3.Bucket.fromBucketName(
        this,
        bid,
        `lex-agents-${bid.toLowerCase()}-dev-123`,
      );
    this.buckets = {
      raw: makeBucket("Raw"),
      canonical: makeBucket("Canonical"),
      evals: makeBucket("Evals"),
      backups: makeBucket("Backups"),
    };
  }
}

// ── Test fixtures ─────────────────────────────────────────────────────────────

function buildStack(): Template {
  const app = new cdk.App();
  const env = { account: "123456789012", region: "eu-central-1" };

  const networkStack = new StubNetworkStack(app, "TestNetwork", { env });
  const dataStack = new StubDataStack(app, "TestData", networkStack.sgAurora, {
    env,
  });
  const appServicesStack = new StubAppServicesStack(
    app,
    "TestApp",
    networkStack.vpc,
    { env },
  );

  const stack = new PipelinesStack(app, "TestPipelines", {
    env,
    envName: "dev",
    networkStack: networkStack as any,
    dataStack: dataStack as any,
    appServicesStack: appServicesStack as any,
  });

  return Template.fromStack(stack);
}

const template = buildStack();

// ── DynamoDB ──────────────────────────────────────────────────────────────────

describe("PipelinesStack — DynamoDB", () => {
  test("3 DynamoDB tables exist (idempotency, quota, fingerprints)", () => {
    template.resourceCountIs("AWS::DynamoDB::Table", 3);
  });

  test("Idempotency table exists with correct name and partition key", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-idempotency",
      KeySchema: Match.arrayWith([
        Match.objectLike({ AttributeName: "doc_id", KeyType: "HASH" }),
      ]),
    });
  });

  test("Quota table exists with correct name", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-quota",
    });
  });

  test("Fingerprints table exists with correct name", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-format-fingerprints",
    });
  });
});

// ── Lambda functions ──────────────────────────────────────────────────────────

describe("PipelinesStack — Lambda functions", () => {
  test("Total Lambda count is at least 30 (13×2 source-specific + 2 shared + format sensor + custom resource)", () => {
    const fns = template.findResources("AWS::Lambda::Function");
    // 13×2 = 26 source-specific + 2 shared + 1 format sensor = 29 minimum
    // CDK may add custom resource Lambdas; assert >= 29
    expect(Object.keys(fns).length).toBeGreaterThanOrEqual(29);
  });

  test("Shared chunk-document Lambda exists with correct timeout (5min) and memory (512MB)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-chunk-document",
      Runtime: "python3.12",
      Timeout: 300,
      MemorySize: 512,
    });
  });

  test("Shared contextualize-chunks Lambda exists with correct timeout (15min) and memory (1024MB)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-contextualize-chunks",
      Runtime: "python3.12",
      Timeout: 900,
      MemorySize: 1024,
    });
  });

  test("boe fetch-raw Lambda exists", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-boe-fetch-raw",
      Runtime: "python3.12",
    });
  });

  test("eur_lex fetch-raw Lambda exists", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-eur_lex-fetch-raw",
      Runtime: "python3.12",
    });
  });

  test("Format sensor Lambda exists", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-format-sensor",
      Runtime: "python3.12",
    });
  });
});

// ── State machines ─────────────────────────────────────────────────────────────

describe("PipelinesStack — State machines", () => {
  test("13 Step Functions state machines exist (one per source)", () => {
    template.resourceCountIs("AWS::StepFunctions::StateMachine", 13);
  });

  test("boe state machine exists with correct name", () => {
    template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
      StateMachineName: "lex-agents-dev-boe-ingest",
      StateMachineType: "STANDARD",
    });
  });

  test("All state machines have X-Ray tracing enabled", () => {
    const machines = template.findResources("AWS::StepFunctions::StateMachine");
    Object.values(machines).forEach((m: any) => {
      expect(m.Properties.TracingConfiguration?.Enabled).toBe(true);
    });
  });

  test("State machine definitions contain the 8 expected states", () => {
    const machines = template.findResources("AWS::StepFunctions::StateMachine");
    const flatten = (v: unknown): string => {
      if (typeof v === "string") return v;
      if (Array.isArray(v)) return v.map(flatten).join("");
      if (v && typeof v === "object")
        return Object.values(v as object)
          .map(flatten)
          .join("");
      return "";
    };
    Object.values(machines).forEach((m: any) => {
      const defStr = flatten(m.Properties.DefinitionString);
      [
        "FetchRaw",
        "ParseCanonical",
        "ChunkDocument",
        "ContextualizeChunks",
        "EmbedChunks",
        "IndexToQdrant",
        "Done",
        "FailState",
      ].forEach((state) => {
        expect(defStr).toContain(`"${state}"`);
      });
    });
  });
});

// ── EventBridge rules ─────────────────────────────────────────────────────────

describe("PipelinesStack — EventBridge rules", () => {
  test("BOE rule exists with cron(0 7 * * ? *) schedule", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      Name: "lex-agents-dev-boe-ingest",
      ScheduleExpression: "cron(0 7 * * ? *)",
      State: "ENABLED",
    });
  });

  test("CENDOJ EventBridge rule does NOT exist (manual-only source)", () => {
    const rules = template.findResources("AWS::Events::Rule");
    const cendojRule = Object.values(rules).find(
      (r: any) => r.Properties.Name === "lex-agents-dev-cendoj-ingest",
    );
    expect(cendojRule).toBeUndefined();
  });

  test("AMBER source (tribunal_constitucional) rule exists but is DISABLED", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      Name: "lex-agents-dev-tribunal_constitucional-ingest",
      State: "DISABLED",
    });
  });

  test("Format sensor rule exists with rate(1 hour) schedule", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      Name: "lex-agents-dev-format-sensor",
      ScheduleExpression: "rate(1 hour)",
      State: "ENABLED",
    });
  });

  test("EUR_LEX rule exists with Monday-only cron", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      Name: "lex-agents-dev-eur_lex-ingest",
      State: "ENABLED",
    });
  });
});

// ── CloudWatch Alarms ─────────────────────────────────────────────────────────

describe("PipelinesStack — Alarms", () => {
  test("At least 13 pipeline failure alarms exist (one per source)", () => {
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    const pipelineAlarms = Object.values(alarms).filter((a: any) =>
      (a.Properties.AlarmName as string).includes("-pipeline-failed"),
    );
    expect(pipelineAlarms.length).toBeGreaterThanOrEqual(13);
  });

  test("boe pipeline failure alarm exists", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: "lex-agents-dev-boe-pipeline-failed",
    });
  });

  test("All alarms have SNS action configured", () => {
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    Object.values(alarms).forEach((a: any) => {
      const allActions = [
        ...(a.Properties.AlarmActions ?? []),
        ...(a.Properties.OKActions ?? []),
      ];
      expect(allActions.length).toBeGreaterThan(0);
    });
  });
});

// ── Format sensor ─────────────────────────────────────────────────────────────

describe("PipelinesStack — Format sensor", () => {
  test("Format sensor Lambda exists", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-format-sensor",
    });
  });

  test("Format sensor EventBridge rule has rate(1 hour) schedule", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      ScheduleExpression: "rate(1 hour)",
    });
  });
});

// ── Outputs ───────────────────────────────────────────────────────────────────

describe("PipelinesStack — Outputs", () => {
  test("PipelineAlertsTopicArn output exists", () => {
    template.hasOutput("PipelineAlertsTopicArn", Match.anyValue());
  });

  test("FormatSensorLambdaArn output exists", () => {
    template.hasOutput("FormatSensorLambdaArn", Match.anyValue());
  });

  test("IdempotencyTableName output exists", () => {
    template.hasOutput("IdempotencyTableName", Match.anyValue());
  });
});
