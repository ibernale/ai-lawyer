import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface AppEcrStackProps extends cdk.StackProps {
  envName: string;
}

export class AppEcrStack extends cdk.Stack {
  public readonly apiRepo: ecr.Repository;
  public readonly webRepo: ecr.Repository;

  constructor(scope: Construct, id: string, props: AppEcrStackProps) {
    super(scope, id, props);
    const { envName } = props;

    const repoDefaults: Partial<ecr.RepositoryProps> = {
      imageScanOnPush: true,
      encryption: ecr.RepositoryEncryption.AES_256,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        // Keep last 10 tagged images
        {
          rulePriority: 1,
          description: 'Keep last 10 tagged images',
          tagStatus: ecr.TagStatus.TAGGED,
          tagPrefixList: ['v', 'sha-'],
          maxImageCount: 10,
        },
        // Expire untagged images after 7 days
        {
          rulePriority: 2,
          description: 'Expire untagged images after 7 days',
          tagStatus: ecr.TagStatus.UNTAGGED,
          maxImageAge: cdk.Duration.days(7),
        },
      ],
    };

    this.apiRepo = new ecr.Repository(this, 'ApiRepo', {
      ...repoDefaults,
      repositoryName: `lex-agents-${envName}-api`,
    });

    this.webRepo = new ecr.Repository(this, 'WebRepo', {
      ...repoDefaults,
      repositoryName: `lex-agents-${envName}-web`,
    });

    // ── Outputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ApiRepoUri', {
      value: this.apiRepo.repositoryUri,
      exportName: `${id}-ApiRepoUri`,
      description: 'ECR URI for the FastAPI backend image',
    });

    new cdk.CfnOutput(this, 'WebRepoUri', {
      value: this.webRepo.repositoryUri,
      exportName: `${id}-WebRepoUri`,
      description: 'ECR URI for the Next.js frontend image',
    });

    // cdk-nag suppressions
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-ECR1',
        reason: 'Scan on push is enabled; KMS CMK encryption is a post-demo enhancement.',
      },
    ]);
  }
}
