/**
 * PipelineStack tests.
 *
 * Cross-stack dependency cycles (DataStack ↔ NetworkSpokeStack via Aurora SG
 * rules and KMS key grants) are avoided by using minimal stub stacks that
 * satisfy only the TypeScript interfaces that PipelineStack actually reads at
 * construction time.
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
import { PipelineStack } from "../lib/stacks/pipeline";

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

  const stack = new PipelineStack(app, "TestPipeline", {
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

describe("PipelineStack — DynamoDB", () => {
  test("Idempotency DynamoDB table exists with correct name", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-idempotency",
    });
  });

  test("Idempotency table has correct partition key", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-idempotency",
      KeySchema: Match.arrayWith([
        Match.objectLike({ AttributeName: "doc_id", KeyType: "HASH" }),
      ]),
    });
  });

  test("Idempotency table has TTL configured", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-idempotency",
      TimeToLiveSpecification: {
        AttributeName: "expires_at",
        Enabled: true,
      },
    });
  });

  test("Idempotency table uses PAY_PER_REQUEST billing", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-idempotency",
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  test("Idempotency table has point-in-time recovery enabled", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "lex-agents-dev-pipeline-idempotency",
      PointInTimeRecoverySpecification: {
        PointInTimeRecoveryEnabled: true,
      },
    });
  });
});

// ── Lambda functions ──────────────────────────────────────────────────────────

describe("PipelineStack — Lambda functions", () => {
  test("4 Lambda functions are created (one per pipeline stage)", () => {
    template.resourceCountIs("AWS::Lambda::Function", 4);
  });

  test("fetch-raw Lambda exists with correct timeout and memory", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-fetch-raw",
      Runtime: "python3.12",
      Timeout: 300, // 5 minutes
      MemorySize: 512,
    });
  });

  test("contextualize-chunks Lambda has 15-minute timeout and 1024MB memory", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: "lex-agents-dev-contextualize-chunks",
      Runtime: "python3.12",
      Timeout: 900, // 15 minutes
      MemorySize: 1024,
    });
  });

  test("All Lambda functions have VPC config", () => {
    const functions = template.findResources("AWS::Lambda::Function");
    Object.values(functions).forEach((fn: any) => {
      expect(fn.Properties.VpcConfig).toBeDefined();
      expect(fn.Properties.VpcConfig.SubnetIds.length).toBeGreaterThan(0);
    });
  });

  test("All Lambda functions have X-Ray tracing enabled", () => {
    const functions = template.findResources("AWS::Lambda::Function");
    Object.values(functions).forEach((fn: any) => {
      expect(fn.Properties.TracingConfig?.Mode).toBe("Active");
    });
  });

  test("All Lambda functions inject LEX_ENV environment variable", () => {
    const functions = template.findResources("AWS::Lambda::Function");
    Object.values(functions).forEach((fn: any) => {
      expect(fn.Properties.Environment?.Variables?.LEX_ENV).toBe("dev");
    });
  });
});

// ── Step Functions state machine ──────────────────────────────────────────────

describe("PipelineStack — State machine", () => {
  test("State machine exists with correct name", () => {
    template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
      StateMachineName: "lex-agents-dev-ingest",
      StateMachineType: "STANDARD",
    });
  });

  test("State machine has X-Ray tracing enabled", () => {
    template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
      TracingConfiguration: { Enabled: true },
    });
  });

  test("State machine has logging configured at ERROR level", () => {
    template.hasResourceProperties("AWS::StepFunctions::StateMachine", {
      LoggingConfiguration: Match.objectLike({
        Level: "ERROR",
        Destinations: Match.arrayWith([
          Match.objectLike({
            CloudWatchLogsLogGroup: Match.objectLike({}),
          }),
        ]),
      }),
    });
  });

  test("State machine definition contains all 8 expected states", () => {
    const machines = template.findResources("AWS::StepFunctions::StateMachine");
    const machineList = Object.values(machines);
    expect(machineList.length).toBe(1);

    // DefinitionString is synthesised as Fn::Join because it embeds Lambda ARN
    // tokens. Flatten all string fragments from the join array for inspection.
    const defRaw = (machineList[0] as any).Properties.DefinitionString;
    const flatten = (v: unknown): string => {
      if (typeof v === "string") return v;
      if (Array.isArray(v)) return v.map(flatten).join("");
      if (v && typeof v === "object")
        return Object.values(v as object)
          .map(flatten)
          .join("");
      return "";
    };
    const defStr = flatten(defRaw);
    const expectedStates = [
      "FetchRaw",
      "ParseCanonical",
      "ChunkDocument",
      "ContextualizeChunks",
      "EmbedChunks",
      "IndexToQdrant",
      "Done",
      "FailState",
    ];
    expectedStates.forEach((state) => {
      expect(defStr).toContain(`"${state}"`);
    });
  });

  test("Lambda stages have retry configuration", () => {
    const machines = template.findResources("AWS::StepFunctions::StateMachine");
    const defRaw = (Object.values(machines)[0] as any).Properties
      .DefinitionString;
    const flatten = (v: unknown): string => {
      if (typeof v === "string") return v;
      if (Array.isArray(v)) return v.map(flatten).join("");
      if (v && typeof v === "object")
        return Object.values(v as object)
          .map(flatten)
          .join("");
      return "";
    };
    const defStr = flatten(defRaw);
    expect(defStr).toContain('"Retry"');
    expect(defStr).toContain("Lambda.ServiceException");
  });
});

// ── EventBridge rule ──────────────────────────────────────────────────────────

describe("PipelineStack — EventBridge rule", () => {
  test("Daily EventBridge rule exists", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      Name: "lex-agents-dev-daily-ingest",
      State: "ENABLED",
    });
  });

  test("EventBridge rule has daily 06:00 UTC cron schedule", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      Name: "lex-agents-dev-daily-ingest",
      ScheduleExpression: "cron(0 6 * * ? *)",
    });
  });

  test("EventBridge rule has at least one target", () => {
    const rules = template.findResources("AWS::Events::Rule");
    const rule = Object.values(rules).find(
      (r: any) => r.Properties.Name === "lex-agents-dev-daily-ingest",
    ) as any;
    expect(rule).toBeDefined();
    expect(Array.isArray(rule.Properties.Targets)).toBe(true);
    expect(rule.Properties.Targets.length).toBeGreaterThan(0);
  });
});

// ── Outputs ───────────────────────────────────────────────────────────────────

describe("PipelineStack — Outputs", () => {
  test("StateMachineArn output exists", () => {
    template.hasOutput("StateMachineArn", Match.anyValue());
  });

  test("IdempotencyTableName output exists", () => {
    template.hasOutput("IdempotencyTableName", Match.anyValue());
  });
});
