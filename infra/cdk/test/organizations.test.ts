import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { OrganizationsStack } from "../lib/stacks/organizations";

describe("OrganizationsStack", () => {
  const app = new cdk.App({
    context: { "lexAgents:rootOuId": "r-test0" },
  });
  const stack = new OrganizationsStack(app, "TestOrgStack", {
    env: { account: "111111111111", region: "eu-central-1" },
  });
  const template = Template.fromStack(stack);

  test("creates 3 OUs (Security, Infrastructure, Workloads)", () => {
    template.resourceCountIs("AWS::Organizations::OrganizationalUnit", 3);
  });

  test("creates 4 SCPs", () => {
    template.resourceCountIs("AWS::Organizations::Policy", 4);
  });

  test("DenyNonEuRegions SCP has correct type", () => {
    template.hasResourceProperties("AWS::Organizations::Policy", {
      Type: "SERVICE_CONTROL_POLICY",
      Name: "DenyNonEuRegions",
    });
  });

  test("SCPs reference eu-central-1 and eu-west-1", () => {
    const policies = template.findResources("AWS::Organizations::Policy");
    const denyNonEu = Object.values(policies).find(
      (p: any) => p.Properties.Name === "DenyNonEuRegions",
    );
    expect(denyNonEu).toBeDefined();
    // CfnPolicy.content is synthesised as a plain object (CDK serialises it
    // at deploy time); JSON.parse is not needed here.
    const raw = (denyNonEu as any).Properties.Content;
    const content = typeof raw === "string" ? JSON.parse(raw) : raw;
    const regions =
      content.Statement[0].Condition.StringNotEquals["aws:RequestedRegion"];
    expect(regions).toContain("eu-central-1");
    expect(regions).toContain("eu-west-1");
  });
});
