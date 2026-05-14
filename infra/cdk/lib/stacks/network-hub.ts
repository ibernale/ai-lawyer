import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as route53resolver from 'aws-cdk-lib/aws-route53resolver';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import { HUB_VPC_CIDR } from '../config/environments';
import { VpcWithEndpoints } from '../constructs/vpc-with-endpoints';

export class NetworkHubStack extends cdk.Stack {
  public readonly transitGateway: ec2.CfnTransitGateway;
  public readonly hubVpc: ec2.Vpc;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    // ── Transit Gateway ───────────────────────────────────────────────────
    this.transitGateway = new ec2.CfnTransitGateway(this, 'TransitGateway', {
      description: 'lex-agents hub Transit Gateway',
      dnsSupport: 'enable',
      vpnEcmpSupport: 'enable',
      defaultRouteTableAssociation: 'enable',
      defaultRouteTablePropagation: 'enable',
      tags: [{ key: 'Name', value: 'lex-agents-tgw' }],
    });

    // ── Hub VPC ───────────────────────────────────────────────────────────
    const hubConstruct = new VpcWithEndpoints(this, 'HubVpc', {
      vpcCidr: HUB_VPC_CIDR,
      availabilityZones: [`${this.region}a`, `${this.region}b`], // hub needs only 2 AZs
      natGateways: 0, // Hub VPC is private-only; endpoints serve all attached VPCs
      createPublicSubnets: false,
    });
    this.hubVpc = hubConstruct.vpc;

    // Hub VPC uses PRIVATE_ISOLATED (no NAT gateways); use isolatedSubnets for TGW attachment
    const hubSubnets = this.hubVpc.isolatedSubnets.length > 0
      ? this.hubVpc.isolatedSubnets
      : this.hubVpc.privateSubnets;

    // TGW attachment for hub VPC
    new ec2.CfnTransitGatewayAttachment(this, 'HubTgwAttachment', {
      transitGatewayId: this.transitGateway.ref,
      vpcId: this.hubVpc.vpcId,
      subnetIds: hubSubnets.map(s => s.subnetId),
      tags: [{ key: 'Name', value: 'lex-agents-hub-tgw-attachment' }],
    });

    // ── Route53 Resolver (placeholder for Santander DNS in Fase 10) ───────
    const resolverSg = new ec2.SecurityGroup(this, 'ResolverSg', {
      vpc: this.hubVpc,
      description: 'Route53 Resolver inbound endpoint',
      allowAllOutbound: false,
    });
    resolverSg.addIngressRule(ec2.Peer.ipv4('10.0.0.0/8'), ec2.Port.udp(53), 'DNS from private ranges');
    resolverSg.addIngressRule(ec2.Peer.ipv4('10.0.0.0/8'), ec2.Port.tcp(53), 'DNS TCP from private ranges');

    new route53resolver.CfnResolverEndpoint(this, 'InboundResolver', {
      direction: 'INBOUND',
      ipAddresses: hubSubnets.slice(0, 2).map(s => ({
        subnetId: s.subnetId,
      })),
      securityGroupIds: [resolverSg.securityGroupId],
      name: 'lex-agents-resolver-inbound',
    });

    // Outputs
    new cdk.CfnOutput(this, 'TransitGatewayId', {
      value: this.transitGateway.ref,
      exportName: 'LexAgents-TransitGatewayId',
    });
    new cdk.CfnOutput(this, 'HubVpcId', {
      value: this.hubVpc.vpcId,
      exportName: 'LexAgents-HubVpcId',
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-VPC7',
        reason: 'VPC Flow Logs for the hub VPC are configured post-deploy via AWS CLI to the log-archive S3 bucket. Cross-account reference at synth time would create circular dependencies.',
      },
      {
        id: 'HIPAA.Security-VPCFlowLogsEnabled',
        reason: 'Flow logs configured post-deploy to log-archive S3 bucket via CLI to avoid cross-account synth-time dependencies.',
      },
      {
        id: 'HIPAA.Security-VPCDefaultSecurityGroupClosed',
        reason: 'Hub VPC default SG is not used by any workload. All hub resources use dedicated security groups.',
      },
    ]);
  }
}
