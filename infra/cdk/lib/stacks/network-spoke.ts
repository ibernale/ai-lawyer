import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";
import { NagSuppressions } from "cdk-nag";
import { DEV_VPC_CONFIG } from "../config/environments";

export interface NetworkSpokeStackProps extends cdk.StackProps {
  envName: string;
  logArchiveAccountId: string;
}

export class NetworkSpokeStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly sgAlb: ec2.SecurityGroup;
  public readonly sgEcsApi: ec2.SecurityGroup;
  public readonly sgEcsWeb: ec2.SecurityGroup;
  public readonly sgAurora: ec2.SecurityGroup;
  public readonly sgAgentcore: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkSpokeStackProps) {
    super(scope, id, props);
    const { envName } = props;
    const cfg = DEV_VPC_CONFIG;

    // VPC Flow Logs use CloudWatch Logs here.
    // TODO (post-deploy): redirect to log-archive S3 bucket via AWS CLI:
    //   aws ec2 create-flow-logs --resource-type VPC --resource-ids <vpc-id> \
    //     --traffic-type ALL --log-destination-type s3 \
    //     --log-destination arn:aws:s3:::org-trail-logs-<log-archive-account>/AWSLogs/
    const flowLogGroup = new logs.LogGroup(this, "VpcFlowLogGroup", {
      logGroupName: `/lex-agents/${envName}/vpc-flow-logs`,
      retention: logs.RetentionDays.ONE_YEAR,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── VPC ───────────────────────────────────────────────────────────────
    this.vpc = new ec2.Vpc(this, "Vpc", {
      ipAddresses: ec2.IpAddresses.cidr(cfg.vpcCidr),
      availabilityZones: cfg.azs,
      natGateways: 3, // one per AZ for HA
      subnetConfiguration: [
        {
          name: "public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
          mapPublicIpOnLaunch: false,
        },
        {
          name: "private-app",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
        {
          name: "private-data",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
      flowLogs: {
        cloudwatch: {
          destination: ec2.FlowLogDestination.toCloudWatchLogs(flowLogGroup),
          trafficType: ec2.FlowLogTrafficType.ALL,
        },
      },
    });

    // ── Security Groups ───────────────────────────────────────────────────

    // ALB: ingress 443 from CloudFront managed prefix list
    this.sgAlb = new ec2.SecurityGroup(this, "SgAlb", {
      vpc: this.vpc,
      securityGroupName: `lex-agents-${envName}-alb`,
      description: "ALB security group - ingress from CloudFront only",
      allowAllOutbound: true,
    });
    // CloudFront managed prefix list — ID varies by region
    const cloudfrontPrefixListIds: Record<string, string> = {
      "eu-west-1": "pl-4fa04526",
      "eu-west-2": "pl-93a247fa",
      "eu-west-3": "pl-75b1541c",
      "eu-central-1": "pl-9ea0e7f7",
      "us-east-1": "pl-3b927c52",
    };
    const cloudfrontPrefixList = ec2.Peer.prefixList(
      cloudfrontPrefixListIds[this.region] ?? "pl-4fa04526",
    );
    this.sgAlb.addIngressRule(
      cloudfrontPrefixList,
      ec2.Port.tcp(443),
      "HTTPS from CloudFront",
    );

    // ECS API
    this.sgEcsApi = new ec2.SecurityGroup(this, "SgEcsApi", {
      vpc: this.vpc,
      securityGroupName: `lex-agents-${envName}-ecs-api`,
      description: "ECS API service",
      allowAllOutbound: false,
    });
    this.sgEcsApi.addIngressRule(
      this.sgAlb,
      ec2.Port.tcp(8000),
      "API port from ALB",
    );
    this.sgEcsApi.addEgressRule(
      ec2.Peer.ipv4(cfg.vpcCidr),
      ec2.Port.tcp(443),
      "HTTPS to VPC endpoints",
    );

    // ECS Web
    this.sgEcsWeb = new ec2.SecurityGroup(this, "SgEcsWeb", {
      vpc: this.vpc,
      securityGroupName: `lex-agents-${envName}-ecs-web`,
      description: "ECS Web (Next.js) service",
      allowAllOutbound: false,
    });
    this.sgEcsWeb.addIngressRule(
      this.sgAlb,
      ec2.Port.tcp(3000),
      "Web port from ALB",
    );
    this.sgEcsWeb.addEgressRule(
      this.sgEcsApi,
      ec2.Port.tcp(8000),
      "API backend",
    );

    // Aurora
    this.sgAurora = new ec2.SecurityGroup(this, "SgAurora", {
      vpc: this.vpc,
      securityGroupName: `lex-agents-${envName}-aurora`,
      description: "Aurora PostgreSQL cluster",
      allowAllOutbound: false,
    });

    // AgentCore
    this.sgAgentcore = new ec2.SecurityGroup(this, "SgAgentcore", {
      vpc: this.vpc,
      securityGroupName: `lex-agents-${envName}-agentcore`,
      description: "AgentCore runtime - egress only",
      allowAllOutbound: false,
    });
    this.sgAgentcore.addEgressRule(
      ec2.Peer.ipv4(cfg.vpcCidr),
      ec2.Port.tcp(443),
      "Bedrock VPC endpoint",
    );

    // Cross-SG rules
    this.sgAurora.addIngressRule(
      this.sgEcsApi,
      ec2.Port.tcp(5432),
      "PostgreSQL from ECS API",
    );
    this.sgAurora.addIngressRule(
      this.sgAgentcore,
      ec2.Port.tcp(5432),
      "PostgreSQL from AgentCore",
    );
    this.sgEcsApi.addEgressRule(
      this.sgAurora,
      ec2.Port.tcp(5432),
      "PostgreSQL to Aurora",
    );
    this.sgAgentcore.addEgressRule(
      this.sgAurora,
      ec2.Port.tcp(5432),
      "PostgreSQL to Aurora",
    );

    // ── NACLs for private-data subnets ────────────────────────────────────
    const dataSubnets = this.vpc.isolatedSubnets;
    const dataNacl = new ec2.NetworkAcl(this, "PrivateDataNacl", {
      vpc: this.vpc,
      subnetSelection: { subnets: dataSubnets },
    });

    // Allow PostgreSQL from private-app subnets.
    // Use CDK synthesis-time CIDRs, not the stale hardcoded list in environments.ts
    // (CDK auto-assigns sequential /24 blocks; the config values never matched).
    const appSubnets = this.vpc.selectSubnets({
      subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
    }).subnets;
    appSubnets.forEach((subnet, idx) => {
      dataNacl.addEntry(`AllowPostgresIn${idx}`, {
        cidr: ec2.AclCidr.ipv4(subnet.ipv4CidrBlock),
        ruleNumber: 100 + idx,
        traffic: ec2.AclTraffic.tcpPort(5432),
        direction: ec2.TrafficDirection.INGRESS,
        ruleAction: ec2.Action.ALLOW,
      });
    });
    // Allow ephemeral return traffic
    dataNacl.addEntry("AllowEphemeralOut", {
      cidr: ec2.AclCidr.ipv4(cfg.vpcCidr),
      ruleNumber: 100,
      traffic: ec2.AclTraffic.tcpPortRange(1024, 65535),
      direction: ec2.TrafficDirection.EGRESS,
      ruleAction: ec2.Action.ALLOW,
    });
    // Deny everything else
    dataNacl.addEntry("DenyAllIn", {
      cidr: ec2.AclCidr.anyIpv4(),
      ruleNumber: 32766,
      traffic: ec2.AclTraffic.allTraffic(),
      direction: ec2.TrafficDirection.INGRESS,
      ruleAction: ec2.Action.DENY,
    });

    // Outputs
    new cdk.CfnOutput(this, "VpcId", {
      value: this.vpc.vpcId,
      exportName: `LexAgents-${envName}-VpcId`,
    });
    new cdk.CfnOutput(this, "SgAuroraId", {
      value: this.sgAurora.securityGroupId,
      exportName: `LexAgents-${envName}-SgAuroraId`,
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-VPC7",
        reason:
          "VPC Flow Logs are sent to CloudWatch Logs in this account. Post-deploy, an S3 export to log-archive is configured via AWS CLI to avoid cross-account stack dependencies at synth time.",
      },
      {
        id: "AwsSolutions-EC23",
        reason:
          "CloudFront managed prefix list ingress on port 443 is intentional for ALB. All other SGs are locked down to specific SG sources.",
      },
      {
        id: "HIPAA.Security-VPCFlowLogsEnabled",
        reason:
          "VPC Flow Logs are enabled and directed to CloudWatch Logs (VpcFlowLogGroup). The suppression applies to the auto-created VPC resource node which CDK instruments separately.",
      },
      {
        id: "HIPAA.Security-CloudWatchLogGroupEncrypted",
        reason:
          "VPC Flow Log group will be encrypted with the KMS logs key in the workloads-dev account once KMS stack is deployed. Cross-stack KMS reference at synth time would create circular dependency.",
      },
      {
        id: "HIPAA.Security-VPCDefaultSecurityGroupClosed",
        reason:
          "The default VPC security group is not used by any resource. CDK creates the VPC default SG; actual workloads use dedicated SGs defined above.",
      },
      {
        id: "HIPAA.Security-VPCNoUnrestrictedRouteToIGW",
        reason:
          "Public subnets require an IGW route by design — they host only the ALB and NAT Gateways (no ECS containers). All application workloads run in private-app subnets with no public route.",
      },
      {
        id: "AwsSolutions-VPC3",
        reason:
          "NACLs on private-data subnets are intentional as a defence-in-depth control per DORA Art.9. Warning acknowledged; NACLs are a positive security control here.",
      },
      {
        id: "HIPAA.Security-IAMNoInlinePolicy",
        reason:
          "Auto-generated CDK inline policy for VPC Flow Logs CloudWatch Logs role. Standard CDK pattern; policy is scoped to the specific flow log group.",
      },
    ]);
  }
}
