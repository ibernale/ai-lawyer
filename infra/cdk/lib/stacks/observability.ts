/**
 * ObservabilityStack — Fase 9.2
 *
 * CloudWatch alarms, dashboard, and SNS alerting for the lex-agents dev environment.
 *
 * Alarms:
 *   - API ECS CPU > 80% for 5 min
 *   - API ECS Memory > 85% for 5 min
 *   - Aurora ServerlessDatabaseCapacity > 7 ACU for 10 min
 *   - ALB 5xx target errors > 10 in 5 min
 *   - ALB P99 latency > 10s
 *
 * Dashboard rows:
 *   1. ECS CPU/Memory for api service
 *   2. ALB requests, 5xx count, P99 latency
 *   3. Aurora capacity, connections
 *
 * SNS topic: lex-agents-dev-alerts (no subscriptions yet — add in Fase 10)
 */

import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

import type { NetworkSpokeStack } from './network-spoke';
import type { AppServicesStack } from './app-services';
import type { DataStack } from './data';

export interface ObservabilityStackProps extends cdk.StackProps {
  envName: string;
  networkStack: NetworkSpokeStack;
  appServicesStack: AppServicesStack;
  dataStack: DataStack;
}

export class ObservabilityStack extends cdk.Stack {
  public readonly alertsTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);
    const { envName, appServicesStack, dataStack } = props;

    const clusterName = appServicesStack.cluster.clusterName;
    const apiServiceName = `lex-agents-${envName}-api`;
    const albFullName = appServicesStack.alb.loadBalancerFullName;
    const auroraClusterId = `lex-agents-${envName}`;

    // ── SNS topic ──────────────────────────────────────────────────────────
    this.alertsTopic = new sns.Topic(this, 'AlertsTopic', {
      topicName: `lex-agents-${envName}-alerts`,
      displayName: `lex-agents ${envName} alerts`,
      // Add email/PagerDuty subscriptions in Fase 10
    });

    const alarmAction = new actions.SnsAction(this.alertsTopic);

    // ── Alarm 1: API ECS CPU > 80% for 5 min ──────────────────────────────
    const apiCpuAlarm = new cloudwatch.Alarm(this, 'ApiCpuAlarm', {
      alarmName: `lex-agents-${envName}-api-cpu-high`,
      alarmDescription: 'API ECS service CPU utilisation exceeded 80% for 5 minutes',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ECS',
        metricName: 'CPUUtilization',
        dimensionsMap: {
          ClusterName: clusterName,
          ServiceName: apiServiceName,
        },
        statistic: 'Average',
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
    const apiMemAlarm = new cloudwatch.Alarm(this, 'ApiMemAlarm', {
      alarmName: `lex-agents-${envName}-api-memory-high`,
      alarmDescription: 'API ECS service memory utilisation exceeded 85% for 5 minutes',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ECS',
        metricName: 'MemoryUtilization',
        dimensionsMap: {
          ClusterName: clusterName,
          ServiceName: apiServiceName,
        },
        statistic: 'Average',
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
    const auroraCapacityAlarm = new cloudwatch.Alarm(this, 'AuroraCapacityAlarm', {
      alarmName: `lex-agents-${envName}-aurora-capacity-high`,
      alarmDescription: 'Aurora Serverless capacity approaching maximum (> 7 ACU for 10 minutes)',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/RDS',
        metricName: 'ServerlessDatabaseCapacity',
        dimensionsMap: {
          DBClusterIdentifier: auroraClusterId,
        },
        statistic: 'Maximum',
        period: cdk.Duration.minutes(1),
      }),
      threshold: 7,
      evaluationPeriods: 10,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    auroraCapacityAlarm.addAlarmAction(alarmAction);
    auroraCapacityAlarm.addOkAction(alarmAction);

    // ── Alarm 4: ALB 5xx target errors > 10 in 5 min ──────────────────────
    const alb5xxAlarm = new cloudwatch.Alarm(this, 'Alb5xxAlarm', {
      alarmName: `lex-agents-${envName}-alb-5xx-high`,
      alarmDescription: 'ALB target 5xx error count exceeded 10 in 5 minutes',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ApplicationELB',
        metricName: 'HTTPCode_Target_5XX_Count',
        dimensionsMap: {
          LoadBalancer: albFullName,
        },
        statistic: 'Sum',
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
    const albLatencyAlarm = new cloudwatch.Alarm(this, 'AlbLatencyAlarm', {
      alarmName: `lex-agents-${envName}-alb-latency-p99`,
      alarmDescription: 'ALB target P99 response time exceeded 10 seconds',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ApplicationELB',
        metricName: 'TargetResponseTime',
        dimensionsMap: {
          LoadBalancer: albFullName,
        },
        statistic: 'p99',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 10,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    albLatencyAlarm.addAlarmAction(alarmAction);
    albLatencyAlarm.addOkAction(alarmAction);

    // ── CloudWatch Dashboard ───────────────────────────────────────────────
    const dashboard = new cloudwatch.Dashboard(this, 'Dashboard', {
      dashboardName: `lex-agents-${envName}`,
      periodOverride: cloudwatch.PeriodOverride.AUTO,
    });

    // Row 1 header
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: '## ECS — API Service',
        width: 24,
        height: 1,
      }),
    );

    // Row 1: ECS CPU / Memory
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'API CPU Utilisation (%)',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ECS',
            metricName: 'CPUUtilization',
            dimensionsMap: { ClusterName: clusterName, ServiceName: apiServiceName },
            statistic: 'Average',
            period: cdk.Duration.minutes(1),
            label: 'CPU avg',
          }),
        ],
        leftAnnotations: [{ value: 80, label: 'Alarm threshold', color: '#ff0000' }],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'API Memory Utilisation (%)',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ECS',
            metricName: 'MemoryUtilization',
            dimensionsMap: { ClusterName: clusterName, ServiceName: apiServiceName },
            statistic: 'Average',
            period: cdk.Duration.minutes(1),
            label: 'Memory avg',
          }),
        ],
        leftAnnotations: [{ value: 85, label: 'Alarm threshold', color: '#ff0000' }],
        width: 12,
        height: 6,
      }),
    );

    // Row 2 header
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: '## ALB — Requests & Latency',
        width: 24,
        height: 1,
      }),
    );

    // Row 2: ALB requests, 5xx count, P99 latency
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'ALB Request Count',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApplicationELB',
            metricName: 'RequestCount',
            dimensionsMap: { LoadBalancer: albFullName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
            label: 'Requests',
          }),
        ],
        width: 8,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB 5xx Errors',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApplicationELB',
            metricName: 'HTTPCode_Target_5XX_Count',
            dimensionsMap: { LoadBalancer: albFullName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(5),
            label: '5xx count',
          }),
        ],
        leftAnnotations: [{ value: 10, label: 'Alarm threshold', color: '#ff0000' }],
        width: 8,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB P99 Latency (s)',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApplicationELB',
            metricName: 'TargetResponseTime',
            dimensionsMap: { LoadBalancer: albFullName },
            statistic: 'p99',
            period: cdk.Duration.minutes(5),
            label: 'P99',
          }),
        ],
        leftAnnotations: [{ value: 10, label: 'Alarm threshold', color: '#ff0000' }],
        width: 8,
        height: 6,
      }),
    );

    // Row 3 header
    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: '## Aurora Serverless v2',
        width: 24,
        height: 1,
      }),
    );

    // Row 3: Aurora capacity & connections
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Aurora Serverless Capacity (ACU)',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/RDS',
            metricName: 'ServerlessDatabaseCapacity',
            dimensionsMap: { DBClusterIdentifier: auroraClusterId },
            statistic: 'Maximum',
            period: cdk.Duration.minutes(1),
            label: 'ACU (max)',
          }),
        ],
        leftAnnotations: [{ value: 7, label: 'Alert threshold', color: '#ff9900' }],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: 'Aurora DB Connections',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/RDS',
            metricName: 'DatabaseConnections',
            dimensionsMap: { DBClusterIdentifier: auroraClusterId },
            statistic: 'Average',
            period: cdk.Duration.minutes(1),
            label: 'Connections (avg)',
          }),
        ],
        width: 12,
        height: 6,
      }),
    );

    // Suppress unused variable lint for dataStack (referenced for dependency only)
    void dataStack;

    // ── Outputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'AlertsTopicArn', {
      value: this.alertsTopic.topicArn,
      exportName: `${id}-AlertsTopicArn`,
      description: 'SNS topic for lex-agents alerts',
    });

    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=lex-agents-${envName}`,
      exportName: `${id}-DashboardUrl`,
      description: 'CloudWatch Dashboard URL',
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-SNS2',
        reason: 'SNS topic for ops alerts; no SSE required for alarm notifications in dev environment.',
      },
      {
        id: 'AwsSolutions-SNS3',
        reason: 'No subscriptions added in Fase 9.2; email/PagerDuty subscriptions will be added in Fase 10.',
      },
      {
        id: 'HIPAA.Security-SNSEncryptedKMS',
        reason: 'Ops alerts SNS topic; KMS encryption for SNS will be added in Fase 10 alongside subscriptions.',
      },
    ]);
  }
}
