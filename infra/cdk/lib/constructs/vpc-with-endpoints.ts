import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export interface VpcWithEndpointsProps {
  vpcCidr: string;
  /** Explicit AZ list — avoids CDK context lookups during synth */
  availabilityZones: string[];
  natGateways: number;
  createPublicSubnets?: boolean;
}

export class VpcWithEndpoints extends Construct {
  public readonly vpc: ec2.Vpc;

  constructor(scope: Construct, id: string, props: VpcWithEndpointsProps) {
    super(scope, id);
    const { vpcCidr, availabilityZones, natGateways, createPublicSubnets = true } = props;

    const subnetConfig: ec2.SubnetConfiguration[] = [];
    if (createPublicSubnets) {
      subnetConfig.push({
        name: 'public',
        subnetType: ec2.SubnetType.PUBLIC,
        cidrMask: 24,
        mapPublicIpOnLaunch: false,
      });
    }
    // Use PRIVATE_ISOLATED when natGateways is 0 (no egress path)
    const privateSubnetType = natGateways > 0
      ? ec2.SubnetType.PRIVATE_WITH_EGRESS
      : ec2.SubnetType.PRIVATE_ISOLATED;

    subnetConfig.push({
      name: 'private',
      subnetType: privateSubnetType,
      cidrMask: 24,
    });

    this.vpc = new ec2.Vpc(scope, `${id}Vpc`, {
      ipAddresses: ec2.IpAddresses.cidr(vpcCidr),
      availabilityZones,
      natGateways,
      subnetConfiguration: subnetConfig,
    });

    // Gateway endpoints (free, no per-hour cost)
    this.vpc.addGatewayEndpoint('S3GatewayEndpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });
    this.vpc.addGatewayEndpoint('DynamoDbGatewayEndpoint', {
      service: ec2.GatewayVpcEndpointAwsService.DYNAMODB,
    });

    // Interface endpoints — use L1 CfnVpcEndpoint to avoid CDK context lookups
    // (L2 addInterfaceEndpoint triggers AZ discovery that fails with placeholder account IDs)
    const subnetIds = (this.vpc.isolatedSubnets.length > 0
      ? this.vpc.isolatedSubnets
      : this.vpc.privateSubnets
    ).map(s => s.subnetId);

    const interfaceEndpoints: { id: string; serviceSuffix: string }[] = [
      { id: 'BedrockRuntime',      serviceSuffix: 'bedrock-runtime' },
      { id: 'SecretsManager',      serviceSuffix: 'secretsmanager'  },
      { id: 'Kms',                 serviceSuffix: 'kms'             },
      { id: 'CloudWatchLogs',      serviceSuffix: 'logs'            },
      { id: 'CloudWatchMonitoring',serviceSuffix: 'monitoring'      },
      { id: 'Ssm',                 serviceSuffix: 'ssm'             },
      { id: 'SsmMessages',         serviceSuffix: 'ssmmessages'     },
      { id: 'Ec2Messages',         serviceSuffix: 'ec2messages'     },
      { id: 'EcrApi',              serviceSuffix: 'ecr.api'         },
      { id: 'EcrDkr',              serviceSuffix: 'ecr.dkr'         },
    ];

    interfaceEndpoints.forEach(({ id: endpointId, serviceSuffix }) => {
      new ec2.CfnVPCEndpoint(this, endpointId, {
        vpcId: this.vpc.vpcId,
        serviceName: `com.amazonaws.${cdk.Aws.REGION}.${serviceSuffix}`,
        vpcEndpointType: 'Interface',
        subnetIds,
        privateDnsEnabled: true,
      });
    });
  }
}
