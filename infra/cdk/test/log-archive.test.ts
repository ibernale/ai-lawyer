import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { KmsStack } from "../lib/stacks/kms";
import { LogArchiveStack } from "../lib/stacks/log-archive";

describe("LogArchiveStack", () => {
  const app = new cdk.App();
  const kmsStack = new KmsStack(app, "TestKmsForLogArchive", {
    env: { account: "222222222222", region: "eu-central-1" },
    envName: "logarchive",
    includeWorkloadKeys: false,
  });
  const stack = new LogArchiveStack(app, "TestLogArchiveStack", {
    env: { account: "222222222222", region: "eu-central-1" },
    drRegion: "eu-west-1",
    kmsStack,
  });
  const template = Template.fromStack(stack);

  test("trail bucket has versioning enabled", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      VersioningConfiguration: { Status: "Enabled" },
    });
  });

  test("trail bucket has Object Lock enabled", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      ObjectLockEnabled: true,
    });
  });

  test("trail bucket blocks all public access", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  test("CloudTrail has log file validation enabled", () => {
    template.hasResourceProperties("AWS::CloudTrail::Trail", {
      EnableLogFileValidation: true,
      IsMultiRegionTrail: true,
      IsOrganizationTrail: true,
    });
  });

  test("Athena workgroup enforces configuration", () => {
    template.hasResourceProperties("AWS::Athena::WorkGroup", {
      WorkGroupConfiguration: {
        EnforceWorkGroupConfiguration: true,
      },
    });
  });

  test("CloudWatch log group has 1-year retention", () => {
    template.hasResourceProperties("AWS::Logs::LogGroup", {
      RetentionInDays: 365,
    });
  });
});
