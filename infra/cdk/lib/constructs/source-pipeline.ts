/**
 * SourcePipeline — Fase 9.4
 *
 * Reusable L3 CDK construct that creates one Step Functions state machine,
 * an optional EventBridge schedule, and a CloudWatch failure alarm for a
 * single ingest source.
 *
 * The 8-state ASL structure mirrors the Fase 9.2 pipeline.ts design:
 *   FetchRaw → ParseCanonical → ChunkDocument → ContextualizeChunks
 *   → EmbedChunks → IndexToQdrant → Done / FailState
 */

import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as events from 'aws-cdk-lib/aws-events';
import * as eventsTargets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

export interface SourcePipelineProps {
  /** Source identifier, e.g. "boe", "eur_lex". Used in resource names. */
  source: string;
  envName: string;
  /** EventBridge schedule. Omit for manual-only sources (e.g. cendoj). */
  schedule?: events.Schedule;
  /** Default true. Set false to create the rule in DISABLED state (AMBER sources). */
  scheduleEnabled?: boolean;
  fetchRawFn: lambda.IFunction;
  parseCanonicalFn: lambda.IFunction;
  chunkDocumentFn: lambda.IFunction;
  contextualizeChunksFn: lambda.IFunction;
  /** ECS cluster ARN — used in EmbedChunks / IndexToQdrant ECS RunTask states. */
  clusterArn: string;
  /**
   * Security group IDs for ECS RunTask (EmbedChunks / IndexToQdrant).
   * Pass the SG(s) attached to the API ECS service so Fargate tasks inherit
   * the correct egress rules (Aurora, Qdrant, VPC endpoints).
   * An empty array causes Fargate to use the VPC default SG — avoid.
   */
  ecsTaskSgIds: string[];
  vpc: ec2.IVpc;
  sfnRole: iam.IRole;
  alertTopic: sns.ITopic;
  idempotencyTable: dynamodb.ITable;
}

export class SourcePipeline extends Construct {
  public readonly stateMachine: sfn.CfnStateMachine;

  constructor(scope: Construct, id: string, props: SourcePipelineProps) {
    super(scope, id);

    const {
      source, envName, schedule, scheduleEnabled = true,
      fetchRawFn, parseCanonicalFn, chunkDocumentFn, contextualizeChunksFn,
      clusterArn, vpc, sfnRole, alertTopic,
    } = props;

    // ── CloudWatch Logs for state machine execution history ──────────────────
    const sfnLogGroup = new logs.LogGroup(this, 'SfnLogGroup', {
      logGroupName: `/lex-agents/${envName}/sfn-${source}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── ASL definition ───────────────────────────────────────────────────────
    const aslDefinition = {
      Comment: `lex-agents ${envName} ${source} ingest pipeline`,
      StartAt: 'FetchRaw',
      States: {
        FetchRaw: {
          Type: 'Task',
          Resource: 'arn:aws:states:::lambda:invoke',
          Parameters: {
            FunctionName: fetchRawFn.functionArn,
            'Payload.$': '$',
          },
          ResultPath: '$.fetchRawResult',
          Retry: [
            {
              ErrorEquals: ['Lambda.ServiceException', 'Lambda.AWSLambdaException', 'Lambda.SdkClientException'],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [{ ErrorEquals: ['States.ALL'], Next: 'FailState', ResultPath: '$.error' }],
          Next: 'ParseCanonical',
        },
        ParseCanonical: {
          Type: 'Task',
          Resource: 'arn:aws:states:::lambda:invoke',
          Parameters: {
            FunctionName: parseCanonicalFn.functionArn,
            'Payload.$': '$',
          },
          ResultPath: '$.parseResult',
          Retry: [
            {
              ErrorEquals: ['Lambda.ServiceException', 'Lambda.AWSLambdaException', 'Lambda.SdkClientException'],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [{ ErrorEquals: ['States.ALL'], Next: 'FailState', ResultPath: '$.error' }],
          Next: 'ChunkDocument',
        },
        ChunkDocument: {
          Type: 'Task',
          Resource: 'arn:aws:states:::lambda:invoke',
          Parameters: {
            FunctionName: chunkDocumentFn.functionArn,
            'Payload.$': '$',
          },
          ResultPath: '$.chunkResult',
          Retry: [
            {
              ErrorEquals: ['Lambda.ServiceException', 'Lambda.AWSLambdaException', 'Lambda.SdkClientException'],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [{ ErrorEquals: ['States.ALL'], Next: 'FailState', ResultPath: '$.error' }],
          Next: 'ContextualizeChunks',
        },
        ContextualizeChunks: {
          Type: 'Task',
          Resource: 'arn:aws:states:::lambda:invoke',
          Parameters: {
            FunctionName: contextualizeChunksFn.functionArn,
            'Payload.$': '$',
          },
          ResultPath: '$.contextualizeResult',
          Retry: [
            {
              ErrorEquals: ['Lambda.ServiceException', 'Lambda.AWSLambdaException', 'Lambda.SdkClientException'],
              IntervalSeconds: 5,
              MaxAttempts: 2,
              BackoffRate: 2,
            },
          ],
          Catch: [{ ErrorEquals: ['States.ALL'], Next: 'FailState', ResultPath: '$.error' }],
          Next: 'EmbedChunks',
        },
        EmbedChunks: {
          Type: 'Task',
          Resource: 'arn:aws:states:::ecs:runTask.sync',
          Parameters: {
            Cluster: clusterArn,
            TaskDefinition: `lex-agents-${envName}-api`,
            LaunchType: 'FARGATE',
            NetworkConfiguration: {
              AwsvpcConfiguration: {
                Subnets: vpc.privateSubnets.map(s => s.subnetId),
                SecurityGroups: props.ecsTaskSgIds,
                AssignPublicIp: 'DISABLED',
              },
            },
            Overrides: {
              ContainerOverrides: [
                {
                  Name: 'api',
                  Command: ['python', '-m', 'lex_agents.pipeline.embed_worker'],
                  'Environment.$': '$.embedEnv',
                },
              ],
            },
          },
          ResultPath: '$.embedResult',
          Catch: [{ ErrorEquals: ['States.ALL'], Next: 'FailState', ResultPath: '$.error' }],
          Next: 'IndexToQdrant',
        },
        IndexToQdrant: {
          Type: 'Task',
          Resource: 'arn:aws:states:::ecs:runTask.sync',
          Parameters: {
            Cluster: clusterArn,
            TaskDefinition: `lex-agents-${envName}-api`,
            LaunchType: 'FARGATE',
            NetworkConfiguration: {
              AwsvpcConfiguration: {
                Subnets: vpc.privateSubnets.map(s => s.subnetId),
                SecurityGroups: props.ecsTaskSgIds,
                AssignPublicIp: 'DISABLED',
              },
            },
            Overrides: {
              ContainerOverrides: [
                {
                  Name: 'api',
                  Command: ['python', '-m', 'lex_agents.pipeline.index_worker'],
                  'Environment.$': '$.indexEnv',
                },
              ],
            },
          },
          ResultPath: '$.indexResult',
          Catch: [{ ErrorEquals: ['States.ALL'], Next: 'FailState', ResultPath: '$.error' }],
          Next: 'Done',
        },
        Done: {
          Type: 'Succeed',
        },
        FailState: {
          Type: 'Fail',
          Error: 'PipelineFailed',
          'Cause.$': '$.error',
        },
      },
    };

    // ── CfnStateMachine ──────────────────────────────────────────────────────
    this.stateMachine = new sfn.CfnStateMachine(this, 'StateMachine', {
      stateMachineName: `lex-agents-${envName}-${source}-ingest`,
      stateMachineType: 'STANDARD',
      roleArn: sfnRole.roleArn,
      definitionString: JSON.stringify(aslDefinition),
      loggingConfiguration: {
        destinations: [{ cloudWatchLogsLogGroup: { logGroupArn: sfnLogGroup.logGroupArn } }],
        includeExecutionData: false,
        level: 'ERROR',
      },
      tracingConfiguration: {
        enabled: true,
      },
    });

    // ── EventBridge schedule (optional) ─────────────────────────────────────
    if (schedule !== undefined) {
      const schedulerRole = new iam.Role(this, 'SchedulerRole', {
        assumedBy: new iam.ServicePrincipal('events.amazonaws.com'),
      });
      schedulerRole.addToPolicy(new iam.PolicyStatement({
        sid: 'StartExecution',
        actions: ['states:StartExecution'],
        resources: [this.stateMachine.attrArn],
      }));

      const rule = new events.Rule(this, 'ScheduleRule', {
        ruleName: `lex-agents-${envName}-${source}-ingest`,
        description: `Ingest schedule for ${source} (${envName})`,
        schedule,
        enabled: scheduleEnabled,
      });

      rule.addTarget(
        new eventsTargets.SfnStateMachine(
          sfn.StateMachine.fromStateMachineArn(this, 'SmRef', this.stateMachine.attrArn),
          {
            role: schedulerRole,
            input: events.RuleTargetInput.fromObject({
              source,
              run_date: events.EventField.fromPath('$.time'),
            }),
          },
        ),
      );
    }

    // ── CloudWatch failure alarm ─────────────────────────────────────────────
    const failureAlarm = new cloudwatch.Alarm(this, 'FailureAlarm', {
      alarmName: `lex-agents-${envName}-${source}-pipeline-failed`,
      alarmDescription: `${source} ingest pipeline execution failed`,
      metric: new cloudwatch.Metric({
        namespace: 'AWS/States',
        metricName: 'ExecutionsFailed',
        dimensionsMap: {
          StateMachineArn: this.stateMachine.attrArn,
        },
        statistic: 'Sum',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    failureAlarm.addAlarmAction(new cloudwatchActions.SnsAction(alertTopic));
  }
}
