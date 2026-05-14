import * as cdk from "aws-cdk-lib";
import * as kms from "aws-cdk-lib/aws-kms";
import * as sns from "aws-cdk-lib/aws-sns";
import { Match, Template } from "aws-cdk-lib/assertions";
import { ComplianceStack } from "../lib/stacks/compliance";

function buildStack(): Template {
  const app = new cdk.App();
  const env = { account: "123456789012", region: "eu-central-1" };

  const supportStack = new cdk.Stack(app, "Support", { env });
  const logsKey = new kms.Key(supportStack, "LogsKey");
  const s3Key = new kms.Key(supportStack, "S3Key");
  const alertTopic = new sns.Topic(supportStack, "AlertTopic");

  const stack = new ComplianceStack(app, "TestCompliance", {
    env,
    envName: "dev",
    logsKey,
    s3Key,
    alertTopic,
  });

  return Template.fromStack(stack);
}

const template = buildStack();

describe("ComplianceStack — S3", () => {
  test("compliance-docs bucket exists", () => {
    template.resourceCountIs("AWS::S3::Bucket", 1);
  });

  test("bucket has Object Lock enabled", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      ObjectLockEnabled: true,
    });
  });

  test("bucket blocks public access", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });
});

describe("ComplianceStack — Lambda", () => {
  test("evidence_collector Lambda exists", () => {
    template.resourceCountIs("AWS::Lambda::Function", 1);
  });

  test("Lambda uses Python 3.12", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Runtime: "python3.12",
    });
  });

  test("Lambda has 5-minute timeout", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Timeout: 300,
    });
  });
});

describe("ComplianceStack — Alarm", () => {
  test("ComplianceScore alarm exists", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: "lex-agents-dev-compliance-score-low",
      Threshold: 90,
      ComparisonOperator: "LessThanThreshold",
    });
  });
});

describe("ComplianceStack — Schedule", () => {
  test("daily EventBridge rule exists", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      ScheduleExpression: "cron(0 2 * * ? *)",
    });
  });
});

// Suppress unused import
void Match;
