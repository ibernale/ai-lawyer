import * as cdk from 'aws-cdk-lib';
import * as organizations from 'aws-cdk-lib/aws-organizations';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export class OrganizationsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    // ── OUs ──────────────────────────────────────────────────────────────
    const securityOu = new organizations.CfnOrganizationalUnit(this, 'SecurityOU', {
      name: 'Security',
      parentId: this.node.tryGetContext('lexAgents:rootOuId') ?? 'PLACEHOLDER_ROOT_OU_ID',
    });

    const infraOu = new organizations.CfnOrganizationalUnit(this, 'InfrastructureOU', {
      name: 'Infrastructure',
      parentId: this.node.tryGetContext('lexAgents:rootOuId') ?? 'PLACEHOLDER_ROOT_OU_ID',
    });

    const workloadsOu = new organizations.CfnOrganizationalUnit(this, 'WorkloadsOU', {
      name: 'Workloads',
      parentId: this.node.tryGetContext('lexAgents:rootOuId') ?? 'PLACEHOLDER_ROOT_OU_ID',
    });

    // ── Service Control Policies ──────────────────────────────────────────
    // Note: CfnPolicy.content must be a plain object, not a JSON string.
    // targetIds attaches the SCP to OUs/accounts at CloudFormation level.

    const denyNonEuRegions = new organizations.CfnPolicy(this, 'DenyNonEuRegions', {
      name: 'DenyNonEuRegions',
      type: 'SERVICE_CONTROL_POLICY',
      description: 'Allow only eu-central-1 and eu-west-1 (DORA data residency)',
      content: {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'DenyNonEuRegions',
            Effect: 'Deny',
            NotAction: [
              'iam:*', 'organizations:*', 'support:*', 'trustedadvisor:*',
              'cloudfront:*', 'route53:*', 'wafv2:*', 'shield:*',
            ],
            Resource: '*',
            Condition: {
              StringNotEquals: {
                'aws:RequestedRegion': ['eu-central-1', 'eu-west-1'],
              },
              BoolIfExists: { 'aws:PrincipalIsAWSService': 'false' },
            },
          },
        ],
      },
      targetIds: [securityOu.ref, infraOu.ref, workloadsOu.ref],
    });

    const denyRootUsage = new organizations.CfnPolicy(this, 'DenyRootUsage', {
      name: 'DenyRootUsage',
      type: 'SERVICE_CONTROL_POLICY',
      description: 'Deny root account usage except break-glass scenarios',
      content: {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'DenyRootActions',
            Effect: 'Deny',
            Action: '*',
            Resource: '*',
            Condition: {
              StringEquals: { 'aws:PrincipalArn': ['arn:aws:iam::*:root'] },
              BoolIfExists: { 'aws:MultiFactorAuthPresent': 'false' },
            },
          },
        ],
      },
      targetIds: [workloadsOu.ref],
    });

    const denyUnencryptedStorage = new organizations.CfnPolicy(this, 'DenyUnencryptedStorage', {
      name: 'DenyUnencryptedStorage',
      type: 'SERVICE_CONTROL_POLICY',
      description: 'Deny S3 PutObject without SSE-KMS and EBS without encryption',
      content: {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'DenyS3UnencryptedPutObject',
            Effect: 'Deny',
            Action: 's3:PutObject',
            Resource: '*',
            Condition: {
              StringNotEquals: {
                's3:x-amz-server-side-encryption': 'aws:kms',
              },
            },
          },
          {
            Sid: 'DenyUnencryptedEBSVolume',
            Effect: 'Deny',
            Action: 'ec2:CreateVolume',
            Resource: '*',
            Condition: {
              Bool: { 'ec2:Encrypted': 'false' },
            },
          },
        ],
      },
      targetIds: [workloadsOu.ref],
    });

    const requireMfaSensitiveActions = new organizations.CfnPolicy(this, 'RequireMFASensitiveActions', {
      name: 'RequireMFASensitiveActions',
      type: 'SERVICE_CONTROL_POLICY',
      description: 'Require MFA for IAM/KMS/Organizations write actions',
      content: {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'RequireMFAForSensitiveActions',
            Effect: 'Deny',
            Action: [
              'iam:CreateUser', 'iam:DeleteUser', 'iam:AttachUserPolicy',
              'iam:CreateAccessKey', 'iam:DeleteAccessKey',
              'kms:DeleteAlias', 'kms:ScheduleKeyDeletion', 'kms:DisableKey',
              'organizations:LeaveOrganization', 'organizations:DeleteOrganization',
            ],
            Resource: '*',
            Condition: {
              BoolIfExists: { 'aws:MultiFactorAuthPresent': 'false' },
            },
          },
        ],
      },
      targetIds: [workloadsOu.ref],
    });

    // Suppress unused variable warnings — all policies are intentionally declared
    void denyRootUsage;
    void denyUnencryptedStorage;
    void requireMfaSensitiveActions;

    // Outputs
    new cdk.CfnOutput(this, 'SecurityOuId', { value: securityOu.ref, exportName: 'LexAgents-SecurityOuId' });
    new cdk.CfnOutput(this, 'InfraOuId', { value: infraOu.ref, exportName: 'LexAgents-InfraOuId' });
    new cdk.CfnOutput(this, 'WorkloadsOuId', { value: workloadsOu.ref, exportName: 'LexAgents-WorkloadsOuId' });

    // cdk-nag suppressions
    NagSuppressions.addStackSuppressions(this, [
      { id: 'AwsSolutions-IAM4', reason: 'Organizations SCP policies are not IAM policies on resources' },
      { id: 'AwsSolutions-IAM5', reason: 'SCPs require Resource: * by design to apply org-wide' },
      { id: 'HIPAA.Security-IAMNoInlinePolicy', reason: 'SCPs are not IAM inline policies on identities' },
    ]);
  }
}
