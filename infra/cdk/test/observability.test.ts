/**
 * ObservabilityStack tests.
 *
 * The DataStack → NetworkSpokeStack dependency cycle that occurs when using
 * Template.fromStack() across stacks in the same CDK App is avoided by
 * building ONLY the ObservabilityStack in its own isolated App.
 * AlarmName strings, metric names, and dashboard contents are inspected
 * directly from the synthesised template.
 */

import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { Construct } from 'constructs';
import { ObservabilityStack } from '../lib/stacks/observability';

// ── Stub stacks that satisfy the type contracts without cross-stack grants ─────

/** Minimal stub satisfying the subset of AppServicesStack that ObservabilityStack reads. */
class StubAppServicesStack extends cdk.Stack {
  public readonly cluster: ecs.ICluster;
  public readonly alb: elbv2.IApplicationLoadBalancer;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);
    const vpc = new ec2.Vpc(this, 'Vpc', { maxAzs: 1, natGateways: 0 });
    this.cluster = new ecs.Cluster(this, 'Cluster', { clusterName: 'lex-agents-dev', vpc });
    this.alb = new elbv2.ApplicationLoadBalancer(this, 'Alb', {
      loadBalancerName: 'lex-agents-dev',
      vpc,
      internetFacing: false,
    });
  }
}

/** Minimal stub satisfying the subset of NetworkSpokeStack that ObservabilityStack reads. */
class StubNetworkStack extends cdk.Stack {
  public readonly vpc: ec2.IVpc;
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);
    this.vpc = new ec2.Vpc(this, 'Vpc', { maxAzs: 1, natGateways: 0 });
  }
}

/** Minimal stub satisfying the subset of DataStack that ObservabilityStack reads. */
class StubDataStack extends cdk.Stack {
  public readonly aurora: rds.IDatabaseCluster;
  public readonly dbAppUserSecret: secretsmanager.ISecret;
  public readonly buckets: {
    raw: s3.IBucket; canonical: s3.IBucket; evals: s3.IBucket; backups: s3.IBucket;
  };

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);
    // Stub aurora — only clusterEndpoint.hostname is read by ObservabilityStack
    this.aurora = rds.DatabaseCluster.fromDatabaseClusterAttributes(this, 'Aurora', {
      clusterIdentifier: 'lex-agents-dev',
      clusterEndpointAddress: 'stub.cluster.eu-central-1.rds.amazonaws.com',
      readerEndpointAddress: 'stub.reader.eu-central-1.rds.amazonaws.com',
      instanceEndpointAddresses: [],
      instanceIdentifiers: [],
      port: 5432,
      securityGroups: [],
    });
    this.dbAppUserSecret = secretsmanager.Secret.fromSecretNameV2(
      this, 'DbSecret', '/lex-agents/dev/db/app-user',
    );
    const makeBucket = (bid: string): s3.IBucket =>
      s3.Bucket.fromBucketName(this, bid, `lex-agents-${bid.toLowerCase()}-dev-123456789012`);
    this.buckets = {
      raw: makeBucket('Raw'),
      canonical: makeBucket('Canonical'),
      evals: makeBucket('Evals'),
      backups: makeBucket('Backups'),
    };
  }
}

// ── Test fixtures ─────────────────────────────────────────────────────────────

function buildStack(): Template {
  const app = new cdk.App();
  const env = { account: '123456789012', region: 'eu-central-1' };

  const networkStack = new StubNetworkStack(app, 'TestNetwork', { env });
  const appServicesStack = new StubAppServicesStack(app, 'TestApp', { env });
  const dataStack = new StubDataStack(app, 'TestData', { env });

  const stack = new ObservabilityStack(app, 'TestObservability', {
    env,
    envName: 'dev',
    networkStack: networkStack as any,
    appServicesStack: appServicesStack as any,
    dataStack: dataStack as any,
  });

  return Template.fromStack(stack);
}

// Build once — shared across all describe blocks in this file
const template = buildStack();

// ── SNS topic ─────────────────────────────────────────────────────────────────

describe('ObservabilityStack — SNS', () => {
  test('SNS alerts topic exists with correct name', () => {
    template.hasResourceProperties('AWS::SNS::Topic', {
      TopicName: 'lex-agents-dev-alerts',
      DisplayName: 'lex-agents dev alerts',
    });
  });

  test('Exactly one SNS topic is created', () => {
    template.resourceCountIs('AWS::SNS::Topic', 1);
  });
});

// ── CloudWatch Alarms ─────────────────────────────────────────────────────────

describe('ObservabilityStack — Alarms', () => {
  test('Exactly 5 alarms are created', () => {
    template.resourceCountIs('AWS::CloudWatch::Alarm', 5);
  });

  test('API CPU alarm is configured at 80% threshold', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'lex-agents-dev-api-cpu-high',
      Threshold: 80,
      MetricName: 'CPUUtilization',
      Namespace: 'AWS/ECS',
    });
  });

  test('API Memory alarm is configured at 85% threshold', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'lex-agents-dev-api-memory-high',
      Threshold: 85,
      MetricName: 'MemoryUtilization',
      Namespace: 'AWS/ECS',
    });
  });

  test('Aurora capacity alarm targets > 7 ACU for 10 periods', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'lex-agents-dev-aurora-capacity-high',
      Threshold: 7,
      EvaluationPeriods: 10,
      MetricName: 'ServerlessDatabaseCapacity',
      Namespace: 'AWS/RDS',
    });
  });

  test('ALB 5xx alarm targets > 10 errors', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'lex-agents-dev-alb-5xx-high',
      Threshold: 10,
      MetricName: 'HTTPCode_Target_5XX_Count',
      Namespace: 'AWS/ApplicationELB',
    });
  });

  test('ALB P99 latency alarm targets > 10 seconds', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'lex-agents-dev-alb-latency-p99',
      Threshold: 10,
      MetricName: 'TargetResponseTime',
      Namespace: 'AWS/ApplicationELB',
    });
  });

  test('All alarms have at least one alarm action (SNS)', () => {
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    Object.values(alarms).forEach((alarm: any) => {
      const actions: unknown[] = [
        ...(alarm.Properties.AlarmActions ?? []),
        ...(alarm.Properties.OKActions ?? []),
      ];
      expect(actions.length).toBeGreaterThan(0);
    });
  });
});

// ── CloudWatch Dashboard ──────────────────────────────────────────────────────

describe('ObservabilityStack — Dashboard', () => {
  test('CloudWatch Dashboard exists with correct name', () => {
    template.hasResourceProperties('AWS::CloudWatch::Dashboard', {
      DashboardName: 'lex-agents-dev',
    });
  });

  test('Exactly one dashboard is created', () => {
    template.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
  });

  test('Dashboard body contains ECS CPU and Memory widgets', () => {
    const dashboards = template.findResources('AWS::CloudWatch::Dashboard');
    const dash = Object.values(dashboards)[0] as any;
    // DashboardBody may be a plain string or a Fn::Join token
    const rawBody = dash.Properties.DashboardBody;
    const bodyStr = typeof rawBody === 'string'
      ? rawBody
      : JSON.stringify(rawBody);
    expect(bodyStr).toContain('CPUUtilization');
    expect(bodyStr).toContain('MemoryUtilization');
  });

  test('Dashboard body contains ALB metrics', () => {
    const dashboards = template.findResources('AWS::CloudWatch::Dashboard');
    const dash = Object.values(dashboards)[0] as any;
    const rawBody = dash.Properties.DashboardBody;
    const bodyStr = typeof rawBody === 'string' ? rawBody : JSON.stringify(rawBody);
    expect(bodyStr).toContain('RequestCount');
    expect(bodyStr).toContain('HTTPCode_Target_5XX_Count');
    expect(bodyStr).toContain('TargetResponseTime');
  });

  test('Dashboard body contains Aurora metrics', () => {
    const dashboards = template.findResources('AWS::CloudWatch::Dashboard');
    const dash = Object.values(dashboards)[0] as any;
    const rawBody = dash.Properties.DashboardBody;
    const bodyStr = typeof rawBody === 'string' ? rawBody : JSON.stringify(rawBody);
    expect(bodyStr).toContain('ServerlessDatabaseCapacity');
    expect(bodyStr).toContain('DatabaseConnections');
  });
});

// ── Outputs ───────────────────────────────────────────────────────────────────

describe('ObservabilityStack — Outputs', () => {
  test('AlertsTopicArn output exists', () => {
    template.hasOutput('AlertsTopicArn', Match.anyValue());
  });

  test('DashboardUrl output exists', () => {
    template.hasOutput('DashboardUrl', Match.anyValue());
  });
});

// Suppress unused import warning for cloudwatch (used implicitly via stack)
void (cloudwatch as unknown);
