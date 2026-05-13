import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { NetworkSpokeStack } from '../lib/stacks/network-spoke';

describe('NetworkSpokeStack', () => {
  const app = new cdk.App();
  const stack = new NetworkSpokeStack(app, 'TestNetworkSpokeStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
    envName: 'dev',
    logArchiveAccountId: '222222222222',
  });
  const template = Template.fromStack(stack);

  test('creates exactly 9 subnets (3 types × 3 AZs)', () => {
    template.resourceCountIs('AWS::EC2::Subnet', 9);
  });

  test('creates 3 NAT Gateways (one per AZ)', () => {
    template.resourceCountIs('AWS::EC2::NatGateway', 3);
  });

  test('no security group allows 0.0.0.0/0 on non-443 ports', () => {
    const sgs = template.findResources('AWS::EC2::SecurityGroup');
    Object.values(sgs).forEach((sg: any) => {
      const ingress = sg.Properties.SecurityGroupIngress ?? [];
      ingress.forEach((rule: any) => {
        if (rule.CidrIp === '0.0.0.0/0' || rule.CidrIpv6 === '::/0') {
          // Only 443 is allowed from any CIDR (CloudFront uses prefix list, not CIDR)
          expect(rule.FromPort).toBe(443);
        }
      });
    });
  });

  test('creates NACL for private-data subnets', () => {
    template.resourceCountIs('AWS::EC2::NetworkAcl', 1);
  });

  test('Aurora SG has no direct internet egress', () => {
    const sgs = template.findResources('AWS::EC2::SecurityGroup');
    const auroraSg = Object.values(sgs).find((sg: any) =>
      sg.Properties.GroupDescription?.includes('Aurora PostgreSQL')
    );
    expect(auroraSg).toBeDefined();
    const egress = (auroraSg as any).Properties.SecurityGroupEgress ?? [];
    const hasOpenEgress = egress.some(
      (r: any) => r.CidrIp === '0.0.0.0/0' || r.CidrIpv6 === '::/0'
    );
    expect(hasOpenEgress).toBe(false);
  });
});
