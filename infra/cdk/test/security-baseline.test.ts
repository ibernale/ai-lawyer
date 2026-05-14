import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { SecurityBaselineStack } from '../lib/stacks/security-baseline';

describe('SecurityBaselineStack', () => {
  const app = new cdk.App();
  const stack = new SecurityBaselineStack(app, 'TestSecurityBaselineStack', {
    env: { account: '333333333333', region: 'eu-central-1' },
    managementAccountId: '111111111111',
  });
  const template = Template.fromStack(stack);

  test('GuardDuty detector is enabled', () => {
    template.hasResourceProperties('AWS::GuardDuty::Detector', {
      Enable: true,
    });
  });

  test('Security Hub is enabled', () => {
    template.resourceCountIs('AWS::SecurityHub::Hub', 1);
  });

  test('SNS topic for security alerts exists', () => {
    template.resourceCountIs('AWS::SNS::Topic', 1);
  });

  test('EventBridge rule for GuardDuty HIGH severity exists', () => {
    template.hasResourceProperties('AWS::Events::Rule', {
      State: 'ENABLED',
    });
  });

  test('Two EventBridge rules (GuardDuty + SecurityHub)', () => {
    template.resourceCountIs('AWS::Events::Rule', 2);
  });
});
