/**
 * ObservabilityStack — Fase 9.2 / 9.4
 *
 * CloudWatch alarms, dashboards, and SNS alerting for the lex-agents dev environment.
 *
 * Alarms (Fase 9.2 — original 5):
 *   - API ECS CPU > 80% for 5 min
 *   - API ECS Memory > 85% for 5 min
 *   - Aurora ServerlessDatabaseCapacity > 7 ACU for 10 min
 *   - ALB 5xx target errors > 10 in 5 min
 *   - ALB P99 latency > 10s
 *
 * Alarms (Fase 9.4 — 2 additional):
 *   - Pipeline execution failed (FormatChangeDetected metric)
 *   - Secret age exceeded (SecretAgeExceeded metric)
 *
 * Dashboards:
 *   - lex-agents-${envName}: ECS, ALB, Aurora
 *   - lex-agents-${envName}-pipeline: Step Functions execution metrics per source
 *   - lex-agents-${envName}-dora: DORA security metrics (MTTD, logins, KMS events)
 *
 * CloudWatch Logs Insights QueryDefinitions: 3 (errors, slow queries, agent invocations)
 *
 * Alert fan-out: EventBridge rule → alert-router Lambda → Slack webhook
 */

import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as costexplorer from "aws-cdk-lib/aws-ce";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as events from "aws-cdk-lib/aws-events";
import * as eventsTargets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as sns from "aws-cdk-lib/aws-sns";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as actions from "aws-cdk-lib/aws-cloudwatch-actions";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";

import type { NetworkSpokeStack } from "./network-spoke";
import type { AppServicesStack } from "./app-services";
import type { DataStack } from "./data";
import type { PipelinesStack } from "./pipelines";

export interface ObservabilityStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
  appServicesStack: AppServicesStack;
  dataStack: DataStack;
  /** Optional — when provided, pipeline metrics are wired up. */
  pipelinesStack?: PipelinesStack;
}

export class ObservabilityStack extends cdk.Stack {
  public readonly alertsTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);
    const { envName, appServicesStack, dataStack, networkStack } = props;

    const clusterName = appServicesStack.cluster.clusterName;
    const apiServiceName = `lex-agents-${envName}-api`;
    const albFullName = appServicesStack.alb.loadBalancerFullName;
    const auroraClusterId = `lex-agents-${envName}`;

    // ── SNS topic ──────────────────────────────────────────────────────────
    this.alertsTopic = new sns.Topic(this, "AlertsTopic", {
      topicName: `lex-agents-${envName}-alerts`,
      displayName: `lex-agents ${envName} alerts`,
      // Add email/PagerDuty subscriptions in Fase 10
    });

    const alarmAction = new actions.SnsAction(this.alertsTopic);

    // ── Alarm 1: API ECS CPU > 80% for 5 min ──────────────────────────────
    const apiCpuAlarm = new cloudwatch.Alarm(this, "ApiCpuAlarm", {
      alarmName: `lex-agents-${envName}-api-cpu-high`,
      alarmDescription:
        "API ECS service CPU utilisation exceeded 80% for 5 minutes",
      metric: new cloudwatch.Metric({
        namespace: "AWS/ECS",
        metricName: "CPUUtilization",
        dimensionsMap: {
          ClusterName: clusterName,
          ServiceName: apiServiceName,
        },
        statistic: "Average",
        period: cdk.Duration.minutes(1),
      }),
      threshold: 80,
      evaluationPeriods: 5,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    apiCpuAlarm.addAlarmAction(alarmAction);
    apiCpuAlarm.addOkAction(alarmAction);

    // ── Alarm 2: API ECS Memory > 85% for 5 min ───────────────────────────
    const apiMemAlarm = new cloudwatch.Alarm(this, "ApiMemAlarm", {
      alarmName: `lex-agents-${envName}-api-memory-high`,
      alarmDescription:
        "API ECS service memory utilisation exceeded 85% for 5 minutes",
      metric: new cloudwatch.Metric({
        namespace: "AWS/ECS",
        metricName: "MemoryUtilization",
        dimensionsMap: {
          ClusterName: clusterName,
          ServiceName: apiServiceName,
        },
        statistic: "Average",
        period: cdk.Duration.minutes(1),
      }),
      threshold: 85,
      evaluationPeriods: 5,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    apiMemAlarm.addAlarmAction(alarmAction);
    apiMemAlarm.addOkAction(alarmAction);

    // ── Alarm 3: Aurora capacity > 7 ACU for 10 min (approaching max of 8) ─
    const auroraCapacityAlarm = new cloudwatch.Alarm(
      this,
      "AuroraCapacityAlarm",
      {
        alarmName: `lex-agents-${envName}-aurora-capacity-high`,
        alarmDescription:
          "Aurora Serverless capacity approaching maximum (> 7 ACU for 10 minutes)",
        metric: new cloudwatch.Metric({
          namespace: "AWS/RDS",
          metricName: "ServerlessDatabaseCapacity",
          dimensionsMap: {
            DBClusterIdentifier: auroraClusterId,
          },
          statistic: "Maximum",
          period: cdk.Duration.minutes(1),
        }),
        threshold: 7,
        evaluationPeriods: 10,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    auroraCapacityAlarm.addAlarmAction(alarmAction);
    auroraCapacityAlarm.addOkAction(alarmAction);

    // ── Alarm 4: ALB 5xx target errors > 10 in 5 min ──────────────────────
    const alb5xxAlarm = new cloudwatch.Alarm(this, "Alb5xxAlarm", {
      alarmName: `lex-agents-${envName}-alb-5xx-high`,
      alarmDescription: "ALB target 5xx error count exceeded 10 in 5 minutes",
      metric: new cloudwatch.Metric({
        namespace: "AWS/ApplicationELB",
        metricName: "HTTPCode_Target_5XX_Count",
        dimensionsMap: {
          LoadBalancer: albFullName,
        },
        statistic: "Sum",
        period: cdk.Duration.minutes(5),
      }),
      threshold: 10,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    alb5xxAlarm.addAlarmAction(alarmAction);
    alb5xxAlarm.addOkAction(alarmAction);

    // ── Alarm 5: ALB P99 latency > 10s ────────────────────────────────────
    const albLatencyAlarm = new cloudwatch.Alarm(this, "AlbLatencyAlarm", {
      alarmName: `lex-agents-${envName}-alb-latency-p99`,
      alarmDescription: "ALB target P99 response time exceeded 10 seconds",
      metric: new cloudwatch.Metric({
        namespace: "AWS/ApplicationELB",
        metricName: "TargetResponseTime",
        dimensionsMap: {
          LoadBalancer: albFullName,
        },
        statistic: "p99",
        period: cdk.Duration.minutes(5),
      }),
      threshold: 10,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    albLatencyAlarm.addAlarmAction(alarmAction);
    albLatencyAlarm.addOkAction(alarmAction);

    // ── Alarm 6 (Fase 9.4): Pipeline execution failed ─────────────────────
    const pipelineFailedAlarm = new cloudwatch.Alarm(
      this,
      "PipelineExecutionFailedAlarm",
      {
        alarmName: `lex-agents-${envName}-pipeline-execution-failed`,
        alarmDescription:
          "Format change detected in one or more pipeline sources",
        metric: new cloudwatch.Metric({
          namespace: "LexAgents/Pipeline",
          metricName: "FormatChangeDetected",
          statistic: "Sum",
          period: cdk.Duration.minutes(5),
        }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    pipelineFailedAlarm.addAlarmAction(alarmAction);

    // ── Alarm 7 (Fase 9.4): Secret age warning ────────────────────────────
    const secretAgeAlarm = new cloudwatch.Alarm(this, "SecretAgeWarnAlarm", {
      alarmName: `lex-agents-${envName}-secret-age-warn`,
      alarmDescription:
        "One or more secrets have not been rotated within the required period",
      metric: new cloudwatch.Metric({
        namespace: "LexAgents/Secrets",
        metricName: "SecretAgeExceeded",
        statistic: "Sum",
        period: cdk.Duration.minutes(5),
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    secretAgeAlarm.addAlarmAction(alarmAction);

    // ── CloudWatch Logs Insights QueryDefinitions (Fase 9.4) ─────────────
    new logs.QueryDefinition(this, "QueryErrorsLastHour", {
      queryDefinitionName: `lex-agents-${envName}-errors-last-hour`,
      queryString: new logs.QueryString({
        fields: ["@timestamp", "@message", "@logStream"],
        filterStatements: ["@message like /ERROR/"],
        sort: "@timestamp desc",
        limit: 100,
      }),
      logGroups: [], // matches /lex-agents/${envName}/* — set at console or via CLI
    });

    new logs.QueryDefinition(this, "QuerySlowQueriesByTrace", {
      queryDefinitionName: `lex-agents-${envName}-slow-queries-by-trace`,
      queryString: new logs.QueryString({
        fields: ["@timestamp", "@message", "traceId"],
        filterStatements: ["@duration > 5000"],
        sort: "@duration desc",
        limit: 50,
      }),
      logGroups: [],
    });

    new logs.QueryDefinition(this, "QueryAgentInvocationsByBranch", {
      queryDefinitionName: `lex-agents-${envName}-agent-invocations-by-branch`,
      queryString: new logs.QueryString({
        fields: ["@timestamp", "branch", "@message"],
        filterStatements: ["@message like /agent_invocation/"],
        sort: "count desc",
        limit: 50,
      }),
      logGroups: [],
    });

    // ── CloudWatch Dashboard — main ────────────────────────────────────────
    const dashboard = new cloudwatch.Dashboard(this, "Dashboard", {
      dashboardName: `lex-agents-${envName}`,
      periodOverride: cloudwatch.PeriodOverride.AUTO,
    });

    // Row 1 header
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: "## ECS — API Service",
        width: 24,
        height: 1,
      }),
    );

    // Row 1: ECS CPU / Memory
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "API CPU Utilisation (%)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ECS",
            metricName: "CPUUtilization",
            dimensionsMap: {
              ClusterName: clusterName,
              ServiceName: apiServiceName,
            },
            statistic: "Average",
            period: cdk.Duration.minutes(1),
            label: "CPU avg",
          }),
        ],
        leftAnnotations: [
          { value: 80, label: "Alarm threshold", color: "#ff0000" },
        ],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "API Memory Utilisation (%)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ECS",
            metricName: "MemoryUtilization",
            dimensionsMap: {
              ClusterName: clusterName,
              ServiceName: apiServiceName,
            },
            statistic: "Average",
            period: cdk.Duration.minutes(1),
            label: "Memory avg",
          }),
        ],
        leftAnnotations: [
          { value: 85, label: "Alarm threshold", color: "#ff0000" },
        ],
        width: 12,
        height: 6,
      }),
    );

    // Row 2 header
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: "## ALB — Requests & Latency",
        width: 24,
        height: 1,
      }),
    );

    // Row 2: ALB requests, 5xx count, P99 latency
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "ALB Request Count",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ApplicationELB",
            metricName: "RequestCount",
            dimensionsMap: { LoadBalancer: albFullName },
            statistic: "Sum",
            period: cdk.Duration.minutes(1),
            label: "Requests",
          }),
        ],
        width: 8,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "ALB 5xx Errors",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ApplicationELB",
            metricName: "HTTPCode_Target_5XX_Count",
            dimensionsMap: { LoadBalancer: albFullName },
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
            label: "5xx count",
          }),
        ],
        leftAnnotations: [
          { value: 10, label: "Alarm threshold", color: "#ff0000" },
        ],
        width: 8,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "ALB P99 Latency (s)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/ApplicationELB",
            metricName: "TargetResponseTime",
            dimensionsMap: { LoadBalancer: albFullName },
            statistic: "p99",
            period: cdk.Duration.minutes(5),
            label: "P99",
          }),
        ],
        leftAnnotations: [
          { value: 10, label: "Alarm threshold", color: "#ff0000" },
        ],
        width: 8,
        height: 6,
      }),
    );

    // Row 3 header
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: "## Aurora Serverless v2",
        width: 24,
        height: 1,
      }),
    );

    // Row 3: Aurora capacity & connections
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Aurora Serverless Capacity (ACU)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/RDS",
            metricName: "ServerlessDatabaseCapacity",
            dimensionsMap: { DBClusterIdentifier: auroraClusterId },
            statistic: "Maximum",
            period: cdk.Duration.minutes(1),
            label: "ACU (max)",
          }),
        ],
        leftAnnotations: [
          { value: 7, label: "Alert threshold", color: "#ff9900" },
        ],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Aurora DB Connections",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/RDS",
            metricName: "DatabaseConnections",
            dimensionsMap: { DBClusterIdentifier: auroraClusterId },
            statistic: "Average",
            period: cdk.Duration.minutes(1),
            label: "Connections (avg)",
          }),
        ],
        width: 12,
        height: 6,
      }),
    );

    // ── Pipeline Dashboard (Fase 9.4) ──────────────────────────────────────
    const pipelineDashboard = new cloudwatch.Dashboard(
      this,
      "PipelineDashboard",
      {
        dashboardName: `lex-agents-${envName}-pipeline`,
        periodOverride: cloudwatch.PeriodOverride.AUTO,
      },
    );

    pipelineDashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: "## Step Functions — Ingest Pipelines",
        width: 24,
        height: 1,
      }),
    );

    pipelineDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Executions Started",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/States",
            metricName: "ExecutionsStarted",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Executions Failed",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/States",
            metricName: "ExecutionsFailed",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Executions Throttled",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/States",
            metricName: "ExecutionThrottled",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Execution Time (ms)",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/States",
            metricName: "ExecutionTime",
            statistic: "Average",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
    );

    // ── DORA Dashboard (Fase 9.4) ──────────────────────────────────────────
    const doraDashboard = new cloudwatch.Dashboard(this, "DoraDashboard", {
      dashboardName: `lex-agents-${envName}-dora`,
      periodOverride: cloudwatch.PeriodOverride.AUTO,
    });

    doraDashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: "## DORA Security Metrics",
        width: 24,
        height: 1,
      }),
    );

    doraDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Login Failures",
        left: [
          new cloudwatch.Metric({
            namespace: "LexAgents/DORA",
            metricName: "LoginFailures",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "MFA Bypass Attempts",
        left: [
          new cloudwatch.Metric({
            namespace: "LexAgents/DORA",
            metricName: "MfaBypassAttempts",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Permission Changes",
        left: [
          new cloudwatch.Metric({
            namespace: "LexAgents/DORA",
            metricName: "PermissionChanges",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "KMS Key Access",
        left: [
          new cloudwatch.Metric({
            namespace: "LexAgents/DORA",
            metricName: "KmsKeyAccess",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
        ],
        width: 6,
        height: 6,
      }),
    );

    // ── Alert router Lambda (Fase 9.4) ─────────────────────────────────────
    // Receives CloudWatch alarm state changes via EventBridge and routes
    // notifications to the configured Slack webhook.
    const alertRouterVpc = networkStack.vpc;
    const sgAlertRouter = new ec2.SecurityGroup(this, "SgAlertRouter", {
      vpc: alertRouterVpc,
      securityGroupName: `lex-agents-${envName}-alert-router`,
      description: "Alert router Lambda security group",
      allowAllOutbound: false,
    });
    // Allow only HTTPS egress — the alert router POSTs to a Slack webhook URL.
    sgAlertRouter.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "HTTPS to Slack webhook",
    );

    // Slack webhook URL stored in Secrets Manager — never in env vars or CFN template.
    // Post-deploy: aws secretsmanager put-secret-value \
    //   --secret-id /lex-agents/${envName}/slack/webhook-url \
    //   --secret-string "https://hooks.slack.com/services/..."
    const slackWebhookSecret = new secretsmanager.Secret(
      this,
      "SlackWebhookSecret",
      {
        secretName: `/lex-agents/${envName}/slack/webhook-url`,
        description: `lex-agents ${envName} Slack webhook URL — populate post-deploy`,
        generateSecretString: {
          secretStringTemplate: JSON.stringify({ url: "" }),
          generateStringKey: "_unused",
          excludePunctuation: true,
          passwordLength: 8,
        },
      },
    );

    const alertRouterFn = new lambda.Function(this, "AlertRouterFn", {
      functionName: `lex-agents-${envName}-alert-router`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      code: lambda.Code.fromInline(`
import json
import os
import urllib.request
import boto3

_sm = boto3.client('secretsmanager')
_webhook_cache: str = ''

def _get_webhook_url(secret_arn: str) -> str:
    global _webhook_cache
    if _webhook_cache:
        return _webhook_cache
    try:
        val = _sm.get_secret_value(SecretId=secret_arn)['SecretString']
        _webhook_cache = json.loads(val).get('url', '')
    except Exception as exc:
        print(f'Failed to fetch webhook secret: {exc}')
    return _webhook_cache

def handler(event, context):
    """Route CloudWatch alarm state changes to Slack."""
    secret_arn = os.environ.get('SLACK_WEBHOOK_SECRET_ARN', '')
    webhook_url = _get_webhook_url(secret_arn) if secret_arn else ''
    if not webhook_url:
        print('Slack webhook not configured — alarm logged only')
        print(json.dumps(event))
        return

    alarm_name = event.get('detail', {}).get('alarmName', 'unknown')
    new_state = event.get('detail', {}).get('state', {}).get('value', 'unknown')
    reason = event.get('detail', {}).get('state', {}).get('reason', '')

    payload = json.dumps({
        'text': f':rotating_light: *{alarm_name}* transitioned to *{new_state}*\\n>{reason}'
    }).encode('utf-8')

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f'Slack response: {resp.status}')
    except Exception as exc:
        print(f'Slack notification failed: {exc}')
`),
      timeout: cdk.Duration.seconds(30),
      memorySize: 128,
      environment: {
        LEX_ENV: envName,
        SLACK_WEBHOOK_SECRET_ARN: slackWebhookSecret.secretArn,
      },
      vpc: alertRouterVpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [sgAlertRouter],
      tracing: lambda.Tracing.ACTIVE,
    });

    // Grant alert router read access to the webhook secret
    slackWebhookSecret.grantRead(alertRouterFn);

    // Grant alert router permission to publish to alertsTopic
    this.alertsTopic.grantPublish(alertRouterFn);

    // EventBridge rule: CloudWatch alarm state changes → alert router Lambda
    const alarmFanoutRule = new events.Rule(this, "AlarmFanoutRule", {
      ruleName: `lex-agents-${envName}-alarm-fanout`,
      description:
        "Route CloudWatch ALARM state changes to alert-router Lambda",
      eventPattern: {
        source: ["aws.cloudwatch"],
        detailType: ["CloudWatch Alarm State Change"],
        detail: {
          state: {
            value: ["ALARM"],
          },
        },
      },
    });

    alarmFanoutRule.addTarget(new eventsTargets.LambdaFunction(alertRouterFn));

    // ── AWS Cost Anomaly Detection (Fase 9.5, ADR 0045) ─────────────────
    // Alerts when a service's daily spend exceeds 2× its 7-day average.
    const anomalyMonitor = new costexplorer.CfnAnomalyMonitor(
      this,
      "ServiceAnomalyMonitor",
      {
        monitorName: `lex-agents-${envName}-service-monitor`,
        monitorType: "DIMENSIONAL",
        monitorDimension: "SERVICE",
      },
    );
    new costexplorer.CfnAnomalySubscription(this, "AnomalySubscription", {
      subscriptionName: `lex-agents-${envName}-anomaly-alerts`,
      monitorArnList: [anomalyMonitor.attrMonitorArn],
      threshold: 20, // 20 USD absolute OR
      // alert if impact > 2× 7-day average
      thresholdExpression:
        '{ "Dimensions": { "Key": "ANOMALY_TOTAL_IMPACT_PERCENTAGE", "Values": ["100"] } }',
      frequency: "DAILY",
      subscribers: [{ address: this.alertsTopic.topicArn, type: "SNS" }],
    });

    // ── FinOps cost dashboard (Fase 9.5) ─────────────────────────────────
    new cloudwatch.Dashboard(this, "FinOpsDashboard", {
      dashboardName: `lex-agents-${envName}-finops`,
      widgets: [
        [
          new cloudwatch.TextWidget({
            markdown: [
              "## FinOps — Cost Breakdown",
              "> **Note:** AWS billing metrics have a 24-hour ingestion delay.",
              "> For real-time estimates use AWS Cost Explorer.",
            ].join("\n"),
            width: 24,
            height: 2,
          }),
        ],
        [
          new cloudwatch.SingleValueWidget({
            title: "Estimated Charges (USD)",
            metrics: [
              new cloudwatch.Metric({
                namespace: "AWS/Billing",
                metricName: "EstimatedCharges",
                dimensionsMap: { Currency: "USD" },
                statistic: "Maximum",
                period: cdk.Duration.days(1),
                region: "us-east-1", // billing metrics only in us-east-1
              }),
            ],
            width: 6,
            height: 4,
          }),
          new cloudwatch.GraphWidget({
            title: "Daily Cost Trend (30d)",
            left: [
              new cloudwatch.Metric({
                namespace: "AWS/Billing",
                metricName: "EstimatedCharges",
                dimensionsMap: { Currency: "USD" },
                statistic: "Maximum",
                period: cdk.Duration.days(1),
                region: "us-east-1",
              }),
            ],
            width: 18,
            height: 4,
          }),
        ],
      ],
    });

    // Suppress unused variable for dataStack (used via dependency only)
    void dataStack;

    // ── Outputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "AlertsTopicArn", {
      value: this.alertsTopic.topicArn,
      exportName: `${id}-AlertsTopicArn`,
      description: "SNS topic for lex-agents alerts",
    });

    new cdk.CfnOutput(this, "DashboardUrl", {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=lex-agents-${envName}`,
      exportName: `${id}-DashboardUrl`,
      description: "CloudWatch Dashboard URL",
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-SNS2",
        reason:
          "SNS topic for ops alerts; no SSE required for alarm notifications in dev environment.",
      },
      {
        id: "AwsSolutions-SNS3",
        reason:
          "No subscriptions added in Fase 9.2; email/PagerDuty subscriptions will be added in Fase 10.",
      },
      {
        id: "HIPAA.Security-SNSEncryptedKMS",
        reason:
          "Ops alerts SNS topic; KMS encryption for SNS will be added in Fase 10 alongside subscriptions.",
      },
      {
        id: "AwsSolutions-L1",
        reason:
          "Alert router Lambda pinned to python3.12. Runtime upgrades tracked via CDK updates.",
      },
      {
        id: "HIPAA.Security-LambdaInsideVPC",
        reason:
          "Alert router Lambda is deployed inside VPC (PRIVATE_WITH_EGRESS) to reach internal endpoints.",
      },
      {
        id: "HIPAA.Security-LambdaConcurrency",
        reason:
          "Alert router Lambda is triggered infrequently by alarm state changes; reserved concurrency not required.",
      },
      {
        id: "HIPAA.Security-LambdaDLQ",
        reason:
          "Alert router is best-effort notification; failed Slack notifications do not require DLQ.",
      },
      {
        id: "AwsSolutions-IAM5",
        reason:
          "cloudwatch:PutMetricData requires wildcard resource per AWS API design.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Inline policy on alert router Lambda for CloudWatch PutMetricData is minimal surface area.",
      },
      {
        id: "AwsSolutions-IAM4",
        reason:
          "AWSLambdaVPCAccessExecutionRole attached by CDK for VPC Lambda execution.",
      },
    ]);
  }
}
