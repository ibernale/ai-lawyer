/**
 * PipelinesStack — Fase 9.4
 *
 * Replaces the single-source PipelineStack (Fase 9.2) with a multi-source
 * pipeline factory that creates one SourcePipeline construct per ingest source
 * (13 sources total per ADR 0049).
 *
 * Resources:
 *   - DynamoDB: idempotency, quota, fingerprints tables
 *   - Shared Step Functions execution role
 *   - Per-source Lambda functions (fetchRaw + parseCanonical per source)
 *   - Shared Lambda functions (chunkDocument, contextualizeChunks)
 *   - 13 SourcePipeline constructs (state machine + optional schedule + alarm)
 *   - Format sensor Lambda (hourly format-change detector)
 *   - SNS alert topic for pipeline failures
 */

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as events from "aws-cdk-lib/aws-events";
import * as eventsTargets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as sns from "aws-cdk-lib/aws-sns";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import type { NetworkSpokeStack } from "./network-spoke";
import type { DataStack } from "./data";
import type { AppServicesStack } from "./app-services";
import { SourcePipeline } from "../constructs/source-pipeline";

export interface PipelinesStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
  dataStack: DataStack;
  appServicesStack: AppServicesStack;
}

export class PipelinesStack extends cdk.Stack {
  public readonly idempotencyTable: dynamodb.Table;
  public readonly quotaTable: dynamodb.Table;
  public readonly fingerprintsTable: dynamodb.Table;
  public readonly alertsTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: PipelinesStackProps) {
    super(scope, id, props);
    const { envName, networkStack, dataStack, appServicesStack } = props;
    const vpc = networkStack.vpc;

    // ── DynamoDB: pipeline idempotency table ────────────────────────────────
    this.idempotencyTable = new dynamodb.Table(this, "IdempotencyTable", {
      tableName: `lex-agents-${envName}-pipeline-idempotency`,
      partitionKey: { name: "doc_id", type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: "expires_at",
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── DynamoDB: CENDOJ quota tracker ───────────────────────────────────────
    this.quotaTable = new dynamodb.Table(this, "QuotaTable", {
      tableName: `lex-agents-${envName}-pipeline-quota`,
      partitionKey: { name: "source", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "date", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── DynamoDB: format change fingerprints ─────────────────────────────────
    this.fingerprintsTable = new dynamodb.Table(this, "FingerprintsTable", {
      tableName: `lex-agents-${envName}-format-fingerprints`,
      partitionKey: { name: "source", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      timeToLiveAttribute: "expires_at",
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── SNS alert topic ──────────────────────────────────────────────────────
    this.alertsTopic = new sns.Topic(this, "AlertsTopic", {
      topicName: `lex-agents-${envName}-pipeline-alerts`,
      displayName: `lex-agents ${envName} pipeline alerts`,
    });

    // ── Lambda security group ────────────────────────────────────────────────
    const sgLambda = new ec2.SecurityGroup(this, "SgLambda", {
      vpc,
      securityGroupName: `lex-agents-${envName}-pipeline-lambda`,
      description:
        "Pipeline Lambda functions — egress to VPC endpoints and internet",
      allowAllOutbound: true,
    });

    const lambdaVpcConfig = {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [sgLambda],
    };

    // Common environment variables for all pipeline Lambdas
    const commonEnv: Record<string, string> = {
      LEX_ENV: envName,
      LOG_LEVEL: "INFO",
      IDEMPOTENCY_TABLE: this.idempotencyTable.tableName,
      DB_SECRET_ARN: dataStack.dbAppUserSecret.secretArn,
      // PipelinesStack already depends on DataStack, so using clusterEndpoint.hostname
      // does not introduce a new cross-stack dependency cycle here.
      DB_HOST: dataStack.aurora.clusterEndpoint.hostname,
      DB_PORT: "5432",
      DB_NAME: "lex_agents",
    };

    const lambdaCodeBase = "../../packages/pipeline_aws/src/lex_pipeline_aws";

    // ── Shared Lambda functions (not source-specific) ────────────────────────
    const chunkDocumentFn = new lambda.Function(this, "ChunkDocumentFn", {
      functionName: `lex-agents-${envName}-chunk-document`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "handler.lambda_handler",
      code: lambda.Code.fromAsset(`${lambdaCodeBase}/chunk_document`),
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: commonEnv,
      ...lambdaVpcConfig,
      tracing: lambda.Tracing.ACTIVE,
    });

    const contextualizeChunksFn = new lambda.Function(
      this,
      "ContextualizeChunksFn",
      {
        functionName: `lex-agents-${envName}-contextualize-chunks`,
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: "handler.lambda_handler",
        code: lambda.Code.fromAsset(`${lambdaCodeBase}/contextualize_chunks`),
        timeout: cdk.Duration.minutes(15),
        memorySize: 1024,
        environment: commonEnv,
        ...lambdaVpcConfig,
        tracing: lambda.Tracing.ACTIVE,
      },
    );

    // Grant shared Lambdas access to the idempotency table and DB secret.
    // Explicit identity policies used instead of grantRead() to avoid adding a
    // resource policy on the KMS CMK that would create a cross-stack cycle:
    //   KmsStack → PipelinesStack/LambdaRole AND PipelinesStack → DataStack → KmsStack
    [
      { fn: chunkDocumentFn, sid: "ChunkDocument" },
      { fn: contextualizeChunksFn, sid: "ContextualizeChunks" },
    ].forEach(({ fn, sid }) => {
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: `DbSecretRead${sid}`,
          actions: [
            "secretsmanager:GetSecretValue",
            "secretsmanager:DescribeSecret",
          ],
          resources: [dataStack.dbAppUserSecret.secretArn],
        }),
      );
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: `DbSecretKmsDecrypt${sid}`,
          actions: ["kms:Decrypt", "kms:DescribeKey"],
          resources: ["*"],
          conditions: {
            StringEquals: {
              "kms:ViaService": `secretsmanager.${this.region}.amazonaws.com`,
            },
          },
        }),
      );
      this.idempotencyTable.grantReadWriteData(fn);
      dataStack.buckets.canonical.grantRead(fn);
    });

    // ── Step Functions execution role (shared across all sources) ────────────
    const sfnRole = new iam.Role(this, "SfnRole", {
      roleName: `lex-agents-${envName}-sfn-ingest`,
      assumedBy: new iam.ServicePrincipal("states.amazonaws.com"),
    });

    sfnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvokeSharedLambdas",
        actions: ["lambda:InvokeFunction"],
        resources: [
          chunkDocumentFn.functionArn,
          contextualizeChunksFn.functionArn,
        ],
      }),
    );

    sfnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "EcsRunTask",
        actions: [
          "ecs:RunTask",
          "ecs:StopTask",
          "ecs:DescribeTasks",
          "iam:PassRole",
        ],
        resources: ["*"],
        conditions: {
          ArnLike: {
            "ecs:cluster": appServicesStack.cluster.clusterArn,
          },
        },
      }),
    );

    sfnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SfnLogs",
        actions: [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups",
        ],
        resources: ["*"],
      }),
    );

    sfnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "XRay",
        actions: [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
        ],
        resources: ["*"],
      }),
    );

    // ── Source definitions ────────────────────────────────────────────────────
    interface SourceDef {
      source: string;
      schedule?: events.Schedule;
      scheduleEnabled?: boolean;
    }

    const sourceDefs: SourceDef[] = [
      {
        source: "boe",
        schedule: events.Schedule.cron({ minute: "0", hour: "7" }),
        scheduleEnabled: true,
      },
      {
        source: "eur_lex",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: true,
      },
      {
        source: "aepd",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "FRI",
        }),
        scheduleEnabled: true,
      },
      {
        source: "edpb",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: true,
      },
      {
        source: "bde",
        schedule: events.Schedule.cron({ minute: "0", hour: "7" }),
        scheduleEnabled: true,
      },
      {
        source: "eba",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: true,
      },
      {
        source: "esma",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: true,
      },
      {
        source: "legislation_uk",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: true,
      },
      {
        source: "fca",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: true,
      },
      {
        source: "tribunal_constitucional",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          weekDay: "MON",
        }),
        scheduleEnabled: false,
      }, // AMBER
      { source: "cendoj" }, // manual only
      {
        source: "inlabs",
        schedule: events.Schedule.cron({ minute: "0", hour: "4" }),
        scheduleEnabled: true,
      }, // STUB
      {
        source: "sidof",
        schedule: events.Schedule.cron({ minute: "0", hour: "13" }),
        scheduleEnabled: true,
      }, // STUB
    ];

    // ── Per-source Lambda functions + SourcePipeline constructs ──────────────
    for (const def of sourceDefs) {
      const { source } = def;
      // Construct ID suffix: capitalise first letter + replace non-alphanumeric with nothing
      const suffix = source
        .replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
        .replace(/^([a-z])/, (_, c: string) => c.toUpperCase());

      const fetchRawFn = new lambda.Function(this, `FetchRaw${suffix}`, {
        functionName: `lex-agents-${envName}-${source}-fetch-raw`,
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: "handler.lambda_handler",
        code: lambda.Code.fromAsset(
          `${lambdaCodeBase}/sources/${source}/fetch_raw`,
        ),
        timeout: cdk.Duration.minutes(5),
        memorySize: 512,
        environment: commonEnv,
        ...lambdaVpcConfig,
        tracing: lambda.Tracing.ACTIVE,
      });

      const parseCanonicalFn = new lambda.Function(
        this,
        `ParseCanonical${suffix}`,
        {
          functionName: `lex-agents-${envName}-${source}-parse-canonical`,
          runtime: lambda.Runtime.PYTHON_3_12,
          handler: "handler.lambda_handler",
          code: lambda.Code.fromAsset(
            `${lambdaCodeBase}/sources/${source}/parse_canonical`,
          ),
          timeout: cdk.Duration.minutes(5),
          memorySize: 512,
          environment: commonEnv,
          ...lambdaVpcConfig,
          tracing: lambda.Tracing.ACTIVE,
        },
      );

      // Grant per-source Lambdas DB secret + idempotency table access.
      // Explicit identity policies used instead of grantRead() — see comment
      // on shared Lambdas above for the reason (KMS cross-stack cycle).
      fetchRawFn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: `DbSecretRead${suffix}FetchRaw`,
          actions: [
            "secretsmanager:GetSecretValue",
            "secretsmanager:DescribeSecret",
          ],
          resources: [dataStack.dbAppUserSecret.secretArn],
        }),
      );
      fetchRawFn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: `DbSecretKmsDecrypt${suffix}FetchRaw`,
          actions: ["kms:Decrypt", "kms:DescribeKey"],
          resources: ["*"],
          conditions: {
            StringEquals: {
              "kms:ViaService": `secretsmanager.${this.region}.amazonaws.com`,
            },
          },
        }),
      );
      this.idempotencyTable.grantReadWriteData(fetchRawFn);
      dataStack.buckets.raw.grantReadWrite(fetchRawFn);

      parseCanonicalFn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: `DbSecretRead${suffix}ParseCanonical`,
          actions: [
            "secretsmanager:GetSecretValue",
            "secretsmanager:DescribeSecret",
          ],
          resources: [dataStack.dbAppUserSecret.secretArn],
        }),
      );
      parseCanonicalFn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: `DbSecretKmsDecrypt${suffix}ParseCanonical`,
          actions: ["kms:Decrypt", "kms:DescribeKey"],
          resources: ["*"],
          conditions: {
            StringEquals: {
              "kms:ViaService": `secretsmanager.${this.region}.amazonaws.com`,
            },
          },
        }),
      );
      this.idempotencyTable.grantReadWriteData(parseCanonicalFn);
      dataStack.buckets.canonical.grantReadWrite(parseCanonicalFn);

      // Allow SFN role to invoke these source-specific Lambdas
      sfnRole.addToPolicy(
        new iam.PolicyStatement({
          sid: `Invoke${suffix}Lambdas`,
          actions: ["lambda:InvokeFunction"],
          resources: [fetchRawFn.functionArn, parseCanonicalFn.functionArn],
        }),
      );

      // Create the SourcePipeline construct
      new SourcePipeline(this, `Pipeline${suffix}`, {
        source,
        envName,
        schedule: def.schedule,
        scheduleEnabled: def.scheduleEnabled,
        fetchRawFn,
        parseCanonicalFn,
        chunkDocumentFn,
        contextualizeChunksFn,
        clusterArn: appServicesStack.cluster.clusterArn,
        // Use the ECS API SG so RunTask Fargate tasks have the correct
        // egress rules (Aurora, Qdrant, VPC endpoints).
        ecsTaskSgIds: [networkStack.sgEcsApi.securityGroupId],
        vpc,
        sfnRole,
        alertTopic: this.alertsTopic,
        idempotencyTable: this.idempotencyTable,
      });
    }

    // ── Format sensor Lambda ─────────────────────────────────────────────────
    const formatSensorFn = new lambda.Function(this, "FormatSensorFn", {
      functionName: `lex-agents-${envName}-format-sensor`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "handler.lambda_handler",
      code: lambda.Code.fromAsset(`${lambdaCodeBase}/format_sensor`),
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      environment: {
        LEX_ENV: envName,
        LOG_LEVEL: "INFO",
        SOURCE_LIST: "boe,eur_lex,aepd,edpb,bde,eba,esma,legislation_uk,fca",
        FINGERPRINTS_TABLE: this.fingerprintsTable.tableName,
        GITHUB_REPO: "ibernale/ai-lawyer",
      },
      ...lambdaVpcConfig,
      tracing: lambda.Tracing.ACTIVE,
    });

    this.fingerprintsTable.grantReadWriteData(formatSensorFn);

    const formatSensorRule = new events.Rule(this, "FormatSensorSchedule", {
      ruleName: `lex-agents-${envName}-format-sensor`,
      description: "Hourly format change sensor",
      schedule: events.Schedule.rate(cdk.Duration.hours(1)),
      enabled: true,
    });
    formatSensorRule.addTarget(
      new eventsTargets.LambdaFunction(formatSensorFn),
    );

    // ── CloudWatch Logs for shared Lambda functions ──────────────────────────
    // (Retention on /aws/lambda/... log groups is controlled by CDK per-function)

    // ── CfnOutputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "PipelineAlertsTopicArn", {
      value: this.alertsTopic.topicArn,
      exportName: `${id}-PipelineAlertsTopicArn`,
      description: "SNS topic ARN for pipeline failure alerts",
    });

    new cdk.CfnOutput(this, "FormatSensorLambdaArn", {
      value: formatSensorFn.functionArn,
      exportName: `${id}-FormatSensorLambdaArn`,
      description: "Format sensor Lambda ARN",
    });

    new cdk.CfnOutput(this, "IdempotencyTableName", {
      value: this.idempotencyTable.tableName,
      exportName: `${id}-IdempotencyTableName`,
      description: "Pipeline idempotency DynamoDB table name",
    });

    // ── cdk-nag suppressions ──────────────────────────────────────────────────
    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM5",
        reason:
          "SFN role needs wildcard for ECS RunTask (cluster-scoped by condition), X-Ray, and CloudWatch Logs delivery APIs.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AWSLambdaVPCAccessExecutionRole attached to pipeline Lambdas by CDK — required for VPC-attached Lambda execution.",
      },
      {
        id: "AwsSolutions-SF1",
        reason:
          "Step Functions logging level set to ERROR; full execution data logging omitted to avoid storing PII.",
      },
      {
        id: "AwsSolutions-SF2",
        reason:
          "X-Ray tracing is enabled on all state machines (tracingConfiguration.enabled = true).",
      },
      {
        id: "AwsSolutions-L1",
        reason:
          "Pipeline Lambda functions pinned to python3.12. Runtime upgrades tracked via CDK updates.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "SFN execution log groups in dev; KMS encryption added in staging/prod.",
      },
      {
        id: "HIPAA.Security-LambdaInsideVPC",
        reason:
          "All pipeline Lambda functions deployed inside VPC (PRIVATE_WITH_EGRESS subnets).",
      },
      {
        id: "HIPAA.Security-LambdaConcurrency",
        reason:
          "Pipeline Lambdas invoked sequentially by Step Functions; reserved concurrency not required.",
      },
      {
        id: "HIPAA.Security-LambdaDLQ",
        reason:
          "Step Functions handles retries and error routing; Lambda DLQ would create duplicate error handling.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline policies on SFN role; moved to managed policies in production.",
      },
      {
        id: "AwsSolutions-SNS2",
        reason:
          "Pipeline alerts SNS topic; SSE not required for alarm notifications in dev.",
      },
      {
        id: "AwsSolutions-SNS3",
        reason:
          "No subscriptions in Fase 9.4; alerting subscriptions added in Fase 10.",
      },
      {
        id: "HIPAA.Security-SNSEncryptedKMS",
        reason: "Pipeline alerts topic; KMS for SNS added in Fase 10.",
      },
      {
        id: "AwsSolutions-DDB3",
        reason:
          "Point-in-time recovery enabled on idempotency table. Quota and fingerprints tables store ephemeral operational data; PITR not required.",
      },
    ]);
  }
}
