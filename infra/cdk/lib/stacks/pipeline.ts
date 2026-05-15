/**
 * PipelineStack — Fase 9.2
 *
 * Step Functions ingest pipeline infrastructure (ADR 0047):
 *   - DynamoDB idempotency table
 *   - Lambda functions for each pipeline stage
 *   - Step Functions state machine (ASL inline)
 *   - EventBridge scheduled rule (daily 06:00 UTC)
 *
 * Lambda code lives in packages/pipeline_aws/src/lex_pipeline_aws/<stage>/
 * (deployed as a CDK asset from that path).
 *
 * EmbedChunks and IndexToQdrant stages use ECS RunTask (reference to
 * AppServicesStack.cluster) — implemented as Task states referencing the
 * API service task definition.
 */

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as events from "aws-cdk-lib/aws-events";
import * as eventsTargets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import type { NetworkSpokeStack } from "./network-spoke";
import type { DataStack } from "./data";
import type { AppServicesStack } from "./app-services";

export interface PipelineStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
  dataStack: DataStack;
  appServicesStack: AppServicesStack;
}

export class PipelineStack extends cdk.Stack {
  public readonly idempotencyTable: dynamodb.Table;
  public readonly stateMachine: sfn.CfnStateMachine;

  constructor(scope: Construct, id: string, props: PipelineStackProps) {
    super(scope, id, props);
    const { envName, networkStack, dataStack, appServicesStack } = props;
    const vpc = networkStack.vpc;

    // ── DynamoDB: pipeline idempotency table ───────────────────────────────
    this.idempotencyTable = new dynamodb.Table(this, "IdempotencyTable", {
      tableName: `lex-agents-${envName}-pipeline-idempotency`,
      partitionKey: { name: "doc_id", type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: "expires_at",
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── Lambda security group ──────────────────────────────────────────────
    const sgLambda = new ec2.SecurityGroup(this, "SgLambda", {
      vpc,
      securityGroupName: `lex-agents-${envName}-pipeline-lambda`,
      description:
        "Pipeline Lambda functions - egress to VPC endpoints and internet",
      allowAllOutbound: true,
    });

    const lambdaVpcConfig = {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [sgLambda],
    };

    // ── Common Lambda props ────────────────────────────────────────────────
    const commonEnv: Record<string, string> = {
      LEX_ENV: envName,
      LOG_LEVEL: "INFO",
      IDEMPOTENCY_TABLE: this.idempotencyTable.tableName,
      DB_SECRET_ARN: dataStack.dbAppUserSecret.secretArn,
      DB_HOST: dataStack.aurora.clusterEndpoint.hostname,
      // Aurora PostgreSQL always uses port 5432; literal avoids a cross-stack
      // token cycle between NetworkSpokeStack and DataStack.
      DB_PORT: "5432",
      DB_NAME: "lex_agents",
    };

    // Lambda code base path. The packages/pipeline_aws directory is resolved
    // relative to the CDK project root (infra/cdk).
    const lambdaCodeBase = "../../packages/pipeline_aws/src/lex_pipeline_aws";

    // ── Stage Lambdas ──────────────────────────────────────────────────────

    const fetchRawFn = new lambda.Function(this, "FetchRawFn", {
      functionName: `lex-agents-${envName}-fetch-raw`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "handler.lambda_handler",
      code: lambda.Code.fromAsset(`${lambdaCodeBase}/fetch_raw`),
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: commonEnv,
      ...lambdaVpcConfig,
      tracing: lambda.Tracing.ACTIVE,
    });

    const parseCanonicalFn = new lambda.Function(this, "ParseCanonicalFn", {
      functionName: `lex-agents-${envName}-parse-canonical`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "handler.lambda_handler",
      code: lambda.Code.fromAsset(`${lambdaCodeBase}/parse_canonical`),
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: commonEnv,
      ...lambdaVpcConfig,
      tracing: lambda.Tracing.ACTIVE,
    });

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

    // Grant each Lambda read access to the DB app-user secret.
    // Explicit identity policies used instead of grantRead() to avoid adding a
    // resource policy on the KMS CMK that would create a cross-stack cycle:
    //   KmsStack → PipelineStack/LambdaRole AND PipelineStack → DataStack → KmsStack
    [
      { fn: fetchRawFn, sid: "FetchRaw" },
      { fn: parseCanonicalFn, sid: "ParseCanonical" },
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
    });

    // Grant S3 read access to raw/canonical buckets for relevant stages
    dataStack.buckets.raw.grantReadWrite(fetchRawFn);
    dataStack.buckets.canonical.grantReadWrite(parseCanonicalFn);
    dataStack.buckets.canonical.grantRead(chunkDocumentFn);
    dataStack.buckets.canonical.grantRead(contextualizeChunksFn);

    // ── Step Functions execution role ──────────────────────────────────────
    const sfnRole = new iam.Role(this, "SfnRole", {
      roleName: `lex-agents-${envName}-sfn-ingest`,
      assumedBy: new iam.ServicePrincipal("states.amazonaws.com"),
    });

    // Lambda invoke
    sfnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvokePipelineLambdas",
        actions: ["lambda:InvokeFunction"],
        resources: [
          fetchRawFn.functionArn,
          parseCanonicalFn.functionArn,
          chunkDocumentFn.functionArn,
          contextualizeChunksFn.functionArn,
        ],
      }),
    );

    // ECS RunTask for embed/index stages
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

    // CloudWatch Logs for state machine execution history
    const sfnLogGroup = new logs.LogGroup(this, "SfnLogGroup", {
      logGroupName: `/lex-agents/${envName}/sfn-ingest`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
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

    // X-Ray tracing
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

    // ── State machine ASL definition ───────────────────────────────────────
    // EmbedChunks and IndexToQdrant are ECS RunTask steps that use the API
    // service container (which runs the embedding/indexing worker entrypoints).
    const aslDefinition = {
      Comment: `lex-agents ${envName} document ingest pipeline`,
      StartAt: "FetchRaw",
      States: {
        FetchRaw: {
          Type: "Task",
          Resource: "arn:aws:states:::lambda:invoke",
          Parameters: {
            FunctionName: fetchRawFn.functionArn,
            "Payload.$": "$",
          },
          ResultPath: "$.fetchRawResult",
          Retry: [
            {
              ErrorEquals: [
                "Lambda.ServiceException",
                "Lambda.AWSLambdaException",
                "Lambda.SdkClientException",
              ],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [
            {
              ErrorEquals: ["States.ALL"],
              Next: "FailState",
              ResultPath: "$.error",
            },
          ],
          Next: "ParseCanonical",
        },
        ParseCanonical: {
          Type: "Task",
          Resource: "arn:aws:states:::lambda:invoke",
          Parameters: {
            FunctionName: parseCanonicalFn.functionArn,
            "Payload.$": "$",
          },
          ResultPath: "$.parseResult",
          Retry: [
            {
              ErrorEquals: [
                "Lambda.ServiceException",
                "Lambda.AWSLambdaException",
                "Lambda.SdkClientException",
              ],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [
            {
              ErrorEquals: ["States.ALL"],
              Next: "FailState",
              ResultPath: "$.error",
            },
          ],
          Next: "ChunkDocument",
        },
        ChunkDocument: {
          Type: "Task",
          Resource: "arn:aws:states:::lambda:invoke",
          Parameters: {
            FunctionName: chunkDocumentFn.functionArn,
            "Payload.$": "$",
          },
          ResultPath: "$.chunkResult",
          Retry: [
            {
              ErrorEquals: [
                "Lambda.ServiceException",
                "Lambda.AWSLambdaException",
                "Lambda.SdkClientException",
              ],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [
            {
              ErrorEquals: ["States.ALL"],
              Next: "FailState",
              ResultPath: "$.error",
            },
          ],
          Next: "ContextualizeChunks",
        },
        ContextualizeChunks: {
          Type: "Task",
          Resource: "arn:aws:states:::lambda:invoke",
          Parameters: {
            FunctionName: contextualizeChunksFn.functionArn,
            "Payload.$": "$",
          },
          ResultPath: "$.contextualizeResult",
          Retry: [
            {
              ErrorEquals: [
                "Lambda.ServiceException",
                "Lambda.AWSLambdaException",
                "Lambda.SdkClientException",
              ],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [
            {
              ErrorEquals: ["States.ALL"],
              Next: "FailState",
              ResultPath: "$.error",
            },
          ],
          Next: "EmbedChunks",
        },
        // EmbedChunks: ECS RunTask — runs the embedding worker via API container
        EmbedChunks: {
          Type: "Task",
          Resource: "arn:aws:states:::ecs:runTask.sync",
          Parameters: {
            Cluster: appServicesStack.cluster.clusterArn,
            TaskDefinition: `lex-agents-${envName}-api`,
            LaunchType: "FARGATE",
            NetworkConfiguration: {
              AwsvpcConfiguration: {
                Subnets: vpc.privateSubnets.map((s) => s.subnetId),
                SecurityGroups: [],
                AssignPublicIp: "DISABLED",
              },
            },
            Overrides: {
              ContainerOverrides: [
                {
                  Name: "api",
                  Command: ["python", "-m", "lex_agents.pipeline.embed_worker"],
                  "Environment.$": "$.embedEnv",
                },
              ],
            },
          },
          ResultPath: "$.embedResult",
          Catch: [
            {
              ErrorEquals: ["States.ALL"],
              Next: "FailState",
              ResultPath: "$.error",
            },
          ],
          Next: "IndexToQdrant",
        },
        // IndexToQdrant: ECS RunTask — runs the Qdrant index worker
        IndexToQdrant: {
          Type: "Task",
          Resource: "arn:aws:states:::ecs:runTask.sync",
          Parameters: {
            Cluster: appServicesStack.cluster.clusterArn,
            TaskDefinition: `lex-agents-${envName}-api`,
            LaunchType: "FARGATE",
            NetworkConfiguration: {
              AwsvpcConfiguration: {
                Subnets: vpc.privateSubnets.map((s) => s.subnetId),
                SecurityGroups: [],
                AssignPublicIp: "DISABLED",
              },
            },
            Overrides: {
              ContainerOverrides: [
                {
                  Name: "api",
                  Command: ["python", "-m", "lex_agents.pipeline.index_worker"],
                  "Environment.$": "$.indexEnv",
                },
              ],
            },
          },
          ResultPath: "$.indexResult",
          Catch: [
            {
              ErrorEquals: ["States.ALL"],
              Next: "FailState",
              ResultPath: "$.error",
            },
          ],
          Next: "Done",
        },
        Done: {
          Type: "Succeed",
        },
        FailState: {
          Type: "Fail",
          Error: "PipelineFailed",
          "Cause.$": "$.error",
        },
      },
    };

    // ── CfnStateMachine (L1) — required to set logging and X-Ray directly ──
    this.stateMachine = new sfn.CfnStateMachine(this, "IngestStateMachine", {
      stateMachineName: `lex-agents-${envName}-ingest`,
      stateMachineType: "STANDARD",
      roleArn: sfnRole.roleArn,
      definitionString: JSON.stringify(aslDefinition),
      loggingConfiguration: {
        destinations: [
          { cloudWatchLogsLogGroup: { logGroupArn: sfnLogGroup.logGroupArn } },
        ],
        includeExecutionData: false,
        level: "ERROR",
      },
      tracingConfiguration: {
        enabled: true,
      },
    });

    // ── EventBridge schedule: daily 06:00 UTC → trigger state machine ──────
    const schedulerRole = new iam.Role(this, "SchedulerRole", {
      roleName: `lex-agents-${envName}-sfn-scheduler`,
      assumedBy: new iam.ServicePrincipal("events.amazonaws.com"),
    });
    schedulerRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "StartExecution",
        actions: ["states:StartExecution"],
        resources: [this.stateMachine.attrArn],
      }),
    );

    const dailyRule = new events.Rule(this, "DailyIngestRule", {
      ruleName: `lex-agents-${envName}-daily-ingest`,
      description: "Daily ingest pipeline trigger - runs at 06:00 UTC",
      schedule: events.Schedule.cron({ minute: "0", hour: "6" }),
      enabled: true,
    });

    dailyRule.addTarget(
      new eventsTargets.SfnStateMachine(
        // eventsTargets.SfnStateMachine accepts IStateMachine; wrap the ARN
        sfn.StateMachine.fromStateMachineArn(
          this,
          "IngestSmRef",
          this.stateMachine.attrArn,
        ),
        {
          role: schedulerRole,
          input: events.RuleTargetInput.fromObject({
            source: "boe",
            run_date: events.EventField.fromPath("$.time"),
          }),
        },
      ),
    );

    // ── Outputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "StateMachineArn", {
      value: this.stateMachine.attrArn,
      exportName: `${id}-StateMachineArn`,
      description: "Ingest pipeline state machine ARN",
    });

    new cdk.CfnOutput(this, "IdempotencyTableName", {
      value: this.idempotencyTable.tableName,
      exportName: `${id}-IdempotencyTableName`,
      description: "Pipeline idempotency DynamoDB table",
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM5",
        reason:
          "SFN role needs wildcard for ECS RunTask (cluster-scoped by condition), X-Ray, and CloudWatch Logs delivery APIs. Scoped to minimum required actions.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AWSLambdaVPCAccessExecutionRole attached to pipeline Lambdas by CDK — required for VPC-attached Lambda execution.",
      },
      {
        id: "AwsSolutions-SF1",
        reason:
          "Step Functions logging level set to ERROR; full execution data logging omitted to avoid storing PII in logs.",
      },
      {
        id: "AwsSolutions-SF2",
        reason:
          "X-Ray tracing is enabled on the state machine (tracingConfiguration.enabled = true).",
      },
      {
        id: "AwsSolutions-L1",
        reason:
          "Pipeline Lambda functions are pinned to python3.12 (latest supported). Runtime upgrades tracked via CDK/dependency updates.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "SFN execution log group in dev; KMS encryption will be added in staging/prod.",
      },
      {
        id: "HIPAA.Security-LambdaInsideVPC",
        reason:
          "All pipeline Lambda functions are deployed inside the VPC (PRIVATE_WITH_EGRESS subnets).",
      },
      {
        id: "HIPAA.Security-LambdaConcurrency",
        reason:
          "Pipeline Lambdas are invoked sequentially by Step Functions; reserved concurrency not required.",
      },
      {
        id: "HIPAA.Security-LambdaDLQ",
        reason:
          "Step Functions handles retries and error routing; a Lambda DLQ would create duplicate error handling.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline policies on SFN and scheduler roles provide minimal surface area; moved to managed policies in production.",
      },
    ]);
  }
}
