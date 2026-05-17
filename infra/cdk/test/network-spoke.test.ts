import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { NetworkSpokeStack } from "../lib/stacks/network-spoke";

describe("NetworkSpokeStack", () => {
  const app = new cdk.App();
  const stack = new NetworkSpokeStack(app, "TestNetworkSpokeStack", {
    env: { account: "123456789012", region: "eu-central-1" },
    envName: "dev",
    logArchiveAccountId: "222222222222",
  });
  const template = Template.fromStack(stack);

  test("creates exactly 9 subnets (3 types × 3 AZs)", () => {
    template.resourceCountIs("AWS::EC2::Subnet", 9);
  });

  test("creates 3 NAT Gateways (one per AZ)", () => {
    template.resourceCountIs("AWS::EC2::NatGateway", 3);
  });

  test("no security group allows 0.0.0.0/0 on non-443 ports", () => {
    const sgs = template.findResources("AWS::EC2::SecurityGroup");
    Object.values(sgs).forEach((sg: any) => {
      const ingress = sg.Properties.SecurityGroupIngress ?? [];
      ingress.forEach((rule: any) => {
        if (rule.CidrIp === "0.0.0.0/0" || rule.CidrIpv6 === "::/0") {
          // Only 443 is allowed from any CIDR (CloudFront uses prefix list, not CIDR)
          expect(rule.FromPort).toBe(443);
        }
      });
    });
  });

  test("creates NACL for private-data subnets", () => {
    template.resourceCountIs("AWS::EC2::NetworkAcl", 1);
  });

  test("NACL allows PostgreSQL ingress from every private-app subnet CIDR", () => {
    // CDK assigns sequential /24 blocks: public 10.10.0-2, private-app 10.10.3-5,
    // private-data 10.10.6-8. The NACL rules must cover the actual assigned CIDRs,
    // not the stale hardcoded list from environments.ts (10.10.10-12.0/24).
    const appSubnets = stack.vpc.selectSubnets({
      subnetType: require("aws-cdk-lib/aws-ec2").SubnetType.PRIVATE_WITH_EGRESS,
    }).subnets;

    const naclEntries = template.findResources("AWS::EC2::NetworkAclEntry");
    const postgresIngressCidrs = Object.values(naclEntries)
      .filter(
        (e: any) =>
          e.Properties.Egress === false &&
          e.Properties.Protocol === 6 &&
          e.Properties.PortRange?.From === 5432 &&
          e.Properties.RuleAction === "allow",
      )
      .map((e: any) => e.Properties.CidrBlock as string);

    expect(postgresIngressCidrs.length).toBe(appSubnets.length);
    appSubnets.forEach((subnet) => {
      expect(postgresIngressCidrs).toContain(subnet.ipv4CidrBlock);
    });
  });

  test("Aurora SG has no direct internet egress", () => {
    const sgs = template.findResources("AWS::EC2::SecurityGroup");
    const auroraSg = Object.values(sgs).find((sg: any) =>
      sg.Properties.GroupDescription?.includes("Aurora PostgreSQL"),
    );
    expect(auroraSg).toBeDefined();
    const egress = (auroraSg as any).Properties.SecurityGroupEgress ?? [];
    const hasOpenEgress = egress.some(
      (r: any) => r.CidrIp === "0.0.0.0/0" || r.CidrIpv6 === "::/0",
    );
    expect(hasOpenEgress).toBe(false);
  });
});
