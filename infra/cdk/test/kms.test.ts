import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { KmsStack } from "../lib/stacks/kms";

describe("KmsStack", () => {
  const app = new cdk.App();
  const stack = new KmsStack(app, "TestKmsStack", {
    env: { account: "123456789012", region: "eu-central-1" },
    envName: "dev",
    includeWorkloadKeys: true,
  });
  const template = Template.fromStack(stack);

  test("creates 5 KMS keys for workload account", () => {
    template.resourceCountIs("AWS::KMS::Key", 5); // logs, rds, s3, secrets, ebs
  });

  test("all KMS keys have rotation enabled", () => {
    template.allResourcesProperties("AWS::KMS::Key", {
      EnableKeyRotation: true,
    });
  });

  test("all KMS keys have 30-day pending window", () => {
    template.allResourcesProperties("AWS::KMS::Key", {
      PendingWindowInDays: 30,
    });
  });

  test("creates 5 aliases", () => {
    template.resourceCountIs("AWS::KMS::Alias", 5);
  });

  test("log key allows CloudTrail service principal", () => {
    const keys = template.findResources("AWS::KMS::Key");
    const logKey = Object.values(keys).find((k: any) =>
      JSON.stringify(k.Properties.Description).includes("logs"),
    );
    expect(logKey).toBeDefined();
    const policy = JSON.stringify(logKey!.Properties.KeyPolicy);
    expect(policy).toContain("cloudtrail.amazonaws.com");
  });
});

describe("KmsStack (log-archive, no workload keys)", () => {
  const app = new cdk.App();
  const stack = new KmsStack(app, "TestLogArchiveKmsStack", {
    env: { account: "123456789012", region: "eu-central-1" },
    envName: "logarchive",
    includeWorkloadKeys: false,
  });
  const template = Template.fromStack(stack);

  test("creates only 1 KMS key (logs)", () => {
    template.resourceCountIs("AWS::KMS::Key", 1);
  });
});
