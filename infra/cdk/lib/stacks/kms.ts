import * as cdk from 'aws-cdk-lib';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface KmsStackProps extends cdk.StackProps {
  envName: string;
  includeWorkloadKeys: boolean;
}

export class KmsStack extends cdk.Stack {
  public readonly rdsKey?: kms.Key;
  public readonly s3Key?: kms.Key;
  public readonly secretsKey?: kms.Key;
  public readonly logsKey: kms.Key;
  public readonly ebsKey?: kms.Key;

  constructor(scope: Construct, id: string, props: KmsStackProps) {
    super(scope, id, props);
    const { envName, includeWorkloadKeys } = props;

    const keyDefaults = {
      enableKeyRotation: true,
      pendingWindow: cdk.Duration.days(30),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    };

    // Logs key — needed by all accounts (CloudWatch Logs, VPC Flow Logs, CloudTrail)
    this.logsKey = new kms.Key(this, 'LogsKey', {
      ...keyDefaults,
      description: `lex-agents ${envName} logs encryption key`,
      alias: `lex-agents-${envName}-logs`,
      policy: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            sid: 'AllowRootAndLogs',
            principals: [
              new iam.AccountRootPrincipal(),
              new iam.ServicePrincipal(`logs.${this.region}.amazonaws.com`),
              new iam.ServicePrincipal('cloudtrail.amazonaws.com'),
              new iam.ServicePrincipal('delivery.logs.amazonaws.com'),
            ],
            actions: ['kms:*'],
            resources: ['*'],
          }),
        ],
      }),
    });

    if (includeWorkloadKeys) {
      // RDS key
      this.rdsKey = new kms.Key(this, 'RdsKey', {
        ...keyDefaults,
        description: `lex-agents ${envName} RDS encryption key`,
        alias: `lex-agents-${envName}-rds`,
      });

      // S3 key
      this.s3Key = new kms.Key(this, 'S3Key', {
        ...keyDefaults,
        description: `lex-agents ${envName} S3 encryption key`,
        alias: `lex-agents-${envName}-s3`,
      });

      // Secrets Manager key
      this.secretsKey = new kms.Key(this, 'SecretsKey', {
        ...keyDefaults,
        description: `lex-agents ${envName} Secrets Manager encryption key`,
        alias: `lex-agents-${envName}-secrets`,
      });

      // EBS key
      this.ebsKey = new kms.Key(this, 'EbsKey', {
        ...keyDefaults,
        description: `lex-agents ${envName} EBS encryption key`,
        alias: `lex-agents-${envName}-ebs`,
        policy: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              sid: 'AllowRootAndEC2',
              principals: [
                new iam.AccountRootPrincipal(),
                new iam.ServicePrincipal('ec2.amazonaws.com'),
              ],
              actions: ['kms:*'],
              resources: ['*'],
            }),
          ],
        }),
      });
    }
  }
}
