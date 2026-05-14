/**
 * LangfuseStack tests — Fase 9.4
 *
 * Validates the self-hosted Langfuse v3 infrastructure (ADR 0048):
 * - Aurora Serverless v2 cluster for Langfuse
 * - ECS Fargate service with ghcr.io/langfuse/langfuse:3 image
 * - Internal ALB
 * - Secrets Manager secrets (nextauth, salt, encryption-key)
 */

import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { Construct } from 'constructs';
import { LangfuseStack } from '../lib/stacks/langfuse';

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
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { name: 'public',       subnetType: ec2.SubnetType.PUBLIC,             cidrMask: 24 },
        { name: 'private-app',  subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
        { name: 'private-data', subnetType: ec2.SubnetType.PRIVATE_ISOLATED,    cidrMask: 24 },
      ],
    });
    const sg = (sid: string): ec2.ISecurityGroup =>
      new ec2.SecurityGroup(this, sid, { vpc: this.vpc, description: sid });
    this.sgAurora    = sg('SgAurora');
    this.sgEcsApi    = sg('SgEcsApi');
    this.sgEcsWeb    = sg('SgEcsWeb');
    this.sgAlb       = sg('SgAlb');
    this.sgAgentcore = sg('SgAgentcore');
  }
}

// ── Test fixtures ─────────────────────────────────────────────────────────────

function buildStack(): Template {
  const app = new cdk.App({
    context: {
      'lexAgents:langfuseAcmCertArn':
        'arn:aws:acm:eu-central-1:123456789012:certificate/test-cert-id',
    },
  });
  const env = { account: '123456789012', region: 'eu-central-1' };

  const networkStack = new StubNetworkStack(app, 'TestNetwork', { env });

  const stack = new LangfuseStack(app, 'TestLangfuse', {
    env,
    envName: 'dev',
    networkStack: networkStack as any,
  });

  return Template.fromStack(stack);
}

const template = buildStack();

// ── Aurora ────────────────────────────────────────────────────────────────────

describe('LangfuseStack — Aurora', () => {
  test('1 Aurora cluster exists', () => {
    template.resourceCountIs('AWS::RDS::DBCluster', 1);
  });

  test('Aurora cluster is storage-encrypted', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      StorageEncrypted: true,
    });
  });

  test('Aurora cluster identifier is correct', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      DBClusterIdentifier: 'langfuse-dev',
    });
  });

  test('Aurora cluster uses PostgreSQL engine', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      Engine: 'aurora-postgresql',
    });
  });

  test('Aurora cluster has 7-day backup retention', () => {
    template.hasResourceProperties('AWS::RDS::DBCluster', {
      BackupRetentionPeriod: 7,
    });
  });
});

// ── ECS ───────────────────────────────────────────────────────────────────────

describe('LangfuseStack — ECS', () => {
  test('ECS cluster exists for Langfuse', () => {
    template.hasResourceProperties('AWS::ECS::Cluster', {
      ClusterName: 'langfuse-dev',
    });
  });

  test('ECS Fargate service exists', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      ServiceName: 'langfuse-web-dev',
    });
  });

  test('Task definition uses ghcr.io/langfuse/langfuse:3 image', () => {
    const taskDefs = template.findResources('AWS::ECS::TaskDefinition');
    const langfuseTaskDef = Object.values(taskDefs).find((td: any) => {
      const containers = td.Properties.ContainerDefinitions ?? [];
      return containers.some((c: any) => c.Image === 'ghcr.io/langfuse/langfuse:3');
    });
    expect(langfuseTaskDef).toBeDefined();
  });

  test('Task definition family is langfuse-web-dev', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Family: 'langfuse-web-dev',
    });
  });

  test('Task definition has X-Ray sidecar container', () => {
    const taskDefs = template.findResources('AWS::ECS::TaskDefinition');
    const langfuseTaskDef = Object.values(taskDefs).find((td: any) => {
      const containers = td.Properties.ContainerDefinitions ?? [];
      return containers.some((c: any) => c.Image === 'ghcr.io/langfuse/langfuse:3');
    });
    expect(langfuseTaskDef).toBeDefined();
    const containers = (langfuseTaskDef as any).Properties.ContainerDefinitions;
    const xrayContainer = containers.find((c: any) =>
      typeof c.Image === 'string' && c.Image.includes('xray-daemon'),
    );
    expect(xrayContainer).toBeDefined();
  });
});

// ── ALB ───────────────────────────────────────────────────────────────────────

describe('LangfuseStack — ALB', () => {
  test('Application Load Balancer exists and is internal', () => {
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::LoadBalancer', {
      Name: 'langfuse-dev',
      Scheme: 'internal',
    });
  });

  test('ALB listener exists', () => {
    // Listener is on port 80 (dev fallback) or 443 (with cert)
    const listeners = template.findResources('AWS::ElasticLoadBalancingV2::Listener');
    expect(Object.keys(listeners).length).toBeGreaterThanOrEqual(1);
  });

  test('Target group health check path is /api/public/health', () => {
    template.hasResourceProperties('AWS::ElasticLoadBalancingV2::TargetGroup', {
      HealthCheckPath: '/api/public/health',
    });
  });
});

// ── Secrets Manager ───────────────────────────────────────────────────────────

describe('LangfuseStack — Secrets', () => {
  test('NextAuth secret exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/langfuse/nextauth-secret',
    });
  });

  test('Salt secret exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/langfuse/salt',
    });
  });

  test('Encryption key secret exists', () => {
    template.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: '/lex-agents/dev/langfuse/encryption-key',
    });
  });

  test('Exactly 3 Langfuse infrastructure secrets exist (not counting DB master)', () => {
    // nextauth-secret, salt, encryption-key = 3 infrastructure secrets
    // The DB master secret is auto-generated by Aurora (different resource)
    const secrets = template.findResources('AWS::SecretsManager::Secret');
    const langfuseInfraSecrets = Object.values(secrets).filter((s: any) => {
      const name: string = s.Properties.Name ?? '';
      return (
        name.includes('nextauth-secret') ||
        name.includes('/langfuse/salt') ||
        name.includes('encryption-key')
      );
    });
    expect(langfuseInfraSecrets.length).toBe(3);
  });
});

// ── Outputs ───────────────────────────────────────────────────────────────────

describe('LangfuseStack — Outputs', () => {
  test('LangfuseInternalUrl output exists', () => {
    template.hasOutput('LangfuseInternalUrl', Match.anyValue());
  });

  test('LangfuseClusterArn output exists', () => {
    template.hasOutput('LangfuseClusterArn', Match.anyValue());
  });

  test('LangfuseAuroraEndpoint output exists', () => {
    template.hasOutput('LangfuseAuroraEndpoint', Match.anyValue());
  });
});
